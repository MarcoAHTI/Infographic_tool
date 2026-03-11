"""
Async wrapper around the Canva Connect API (2026 Edition).

Covers:
    - OAuth2 Authorization Code + PKCE URL generation.
    - Authorization-code and refresh-token exchange.
  - Template search by brand_template_id.
  - Design creation via the Autofill / Design Editing endpoint.
  - Export polling and image download.

All network calls use ``httpx.AsyncClient`` so that the entire orchestration
pipeline can remain non-blocking.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
from urllib.parse import urlencode
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canva API base URL
# ---------------------------------------------------------------------------
CANVA_API_BASE = "https://api.canva.com/rest/v1"
CANVA_AUTH_URL = "https://api.canva.com/rest/v1/oauth/token"
CANVA_AUTHORIZE_URL = "https://www.canva.com/api/oauth/authorize"


_cached_access_token: Optional[str] = None
_cached_refresh_token: Optional[str] = None
_cached_token_expiry_epoch: float = 0.0


class CanvaAuthError(RuntimeError):
    """Raised when Canva authentication cannot be completed."""


def _default_scopes() -> str:
    return os.getenv(
        "CANVA_SCOPES",
        "brandtemplate:content:read asset:write design:content:read "
        "design:content:write brandtemplate:meta:read asset:read brandtemplate:content:write",
    )


def generate_pkce_pair() -> tuple[str, str]:
    """Create a PKCE code_verifier and code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(96)
    challenge = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def generate_state() -> str:
    """Create a cryptographically random state token for CSRF protection."""
    return secrets.token_urlsafe(48)


def build_authorization_url(
    *,
    code_challenge: str,
    state: str,
    redirect_uri: Optional[str] = None,
    scopes: Optional[str] = None,
) -> str:
    """Build Canva OAuth authorization URL for Authorization Code + PKCE."""
    client_id, _ = _get_credentials()
    redirect = redirect_uri or os.getenv("CANVA_REDIRECT_URI", "").strip()
    params = {
        "code_challenge": code_challenge,
        "code_challenge_method": "s256",
        "scope": scopes or _default_scopes(),
        "response_type": "code",
        "client_id": client_id,
        "state": state,
    }
    if redirect:
        params["redirect_uri"] = redirect
    return f"{CANVA_AUTHORIZE_URL}?{urlencode(params)}"


def set_tokens(
    *,
    access_token: str,
    refresh_token: Optional[str] = None,
    expires_in: Optional[int] = None,
) -> None:
    """Store tokens in memory so the current process can reuse them."""
    global _cached_access_token, _cached_refresh_token, _cached_token_expiry_epoch
    _cached_access_token = access_token
    if refresh_token:
        _cached_refresh_token = refresh_token
    if expires_in:
        # Refresh 60 seconds before official expiry.
        _cached_token_expiry_epoch = time.time() + max(expires_in - 60, 30)
    else:
        _cached_token_expiry_epoch = 0.0


async def exchange_authorization_code(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: Optional[str] = None,
) -> Dict[str, Any]:
    """Exchange OAuth authorization code for access + refresh tokens."""
    client_id, client_secret = _get_credentials()
    redirect = redirect_uri or os.getenv("CANVA_REDIRECT_URI", "").strip()

    payload: Dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
    }
    if redirect:
        payload["redirect_uri"] = redirect

    async with httpx.AsyncClient() as client:
        response = await client.post(
            CANVA_AUTH_URL,
            data=payload,
            auth=(client_id, client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if response.status_code >= 400:
            try:
                details = response.json()
            except Exception:
                details = response.text
            raise CanvaAuthError(
                f"Canva authorization_code exchange failed ({response.status_code}): {details}"
            )

        data = response.json()
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in")
        if not access_token:
            raise CanvaAuthError("Canva token response did not include an access_token.")
        set_tokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )
        return data


def _get_credentials() -> tuple[str, str]:
    """Return (client_id, client_secret) from environment variables."""
    client_id = os.getenv("CANVA_CLIENT_ID", "")
    client_secret = os.getenv("CANVA_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise EnvironmentError(
            "CANVA_CLIENT_ID and CANVA_CLIENT_SECRET must be set in your environment."
        )
    return client_id, client_secret


async def get_access_token() -> str:
    """
    Obtain a short-lived OAuth2 access token via client credentials flow.

    Returns
    -------
    str
        Bearer access token for subsequent API calls.
    """
    global _cached_refresh_token

    # Reuse cached token while still valid.
    if _cached_access_token and (_cached_token_expiry_epoch == 0.0 or time.time() < _cached_token_expiry_epoch):
        return _cached_access_token

    # Prefer an already-issued token from PKCE flow if available.
    static_access_token = os.getenv("CANVA_ACCESS_TOKEN", "").strip()
    if static_access_token:
        set_tokens(access_token=static_access_token)
        return static_access_token

    refresh_token = _cached_refresh_token or os.getenv("CANVA_REFRESH_TOKEN", "").strip()
    client_id, client_secret = _get_credentials()

    if not refresh_token:
        raise CanvaAuthError(
            "No CANVA_ACCESS_TOKEN or CANVA_REFRESH_TOKEN configured. "
            "Your Canva app is using OAuth Authorization Code + PKCE; run the auth flow "
            "to obtain tokens and store them in .env."
        )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            CANVA_AUTH_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            auth=(client_id, client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if response.status_code >= 400:
            try:
                details = response.json()
            except Exception:
                details = response.text
            raise CanvaAuthError(
                f"Canva token request failed ({response.status_code}): {details}"
            )

        data = response.json()
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in")
        if not access_token:
            raise CanvaAuthError("Canva token response did not include an access_token.")
        set_tokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )
        return access_token


async def create_design_from_template(
    token: str,
    brand_template_id: str,
    content: Dict[str, Any],
    brand_colors: Dict[str, str],
    brand_font: str,
    logo_placement: str = "bottom-right",
) -> str:
    """
    Create a new Canva design by autofilling a brand template with content.

    Parameters
    ----------
    token:
        Valid Canva OAuth2 access token.
    brand_template_id:
        The Canva brand template to use as a base.
    content:
        Dict with keys: ``headline``, ``data_points``, ``visual_metaphor``.
    brand_colors:
        Dict mapping role → hex colour (e.g. ``{"primary": "#336A88"}``).
    brand_font:
        Font family name for the design.
    logo_placement:
        Where to position the logo (currently informational metadata).

    Returns
    -------
    str
        The newly created design's Canva design ID.
    """
    # Build the autofill data payload according to Canva Connect API spec
    data_points = content.get("data_points", [])
    data_fields = [
        {"name": "headline", "text": {"text": content.get("headline", "")}},
        *[
            {
                "name": f"data_point_{i + 1}",
                "text": {"text": data_points[i] if i < len(data_points) else ""},
            }
            for i in range(5)
        ],
        {"name": "visual_metaphor", "text": {"text": content.get("visual_metaphor", "")}},
    ]

    payload: Dict[str, Any] = {
        "brand_template_id": brand_template_id,
        "title": content.get("headline", "Infographic"),
        "data": data_fields,
        "brand_kit": {
            "colors": [
                {"name": role, "value": hex_color}
                for role, hex_color in brand_colors.items()
            ],
            "fonts": [{"family": brand_font}],
            "logo_placement": logo_placement,
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{CANVA_API_BASE}/autofills",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        # The async autofill job ID is returned; we poll for the design ID
        job_id: str = data.get("job", {}).get("id") or data.get("id", "")
        logger.info("Canva autofill job created: %s", job_id)
        return job_id


async def poll_autofill_job(token: str, job_id: str, max_attempts: int = 20) -> str:
    """
    Poll the Canva autofill job until it completes and return the design ID.

    Parameters
    ----------
    token:
        Valid Canva OAuth2 access token.
    job_id:
        The autofill job ID returned by :func:`create_design_from_template`.
    max_attempts:
        Maximum number of polling attempts (each ~3 s apart).

    Returns
    -------
    str
        The completed Canva design ID.

    Raises
    ------
    TimeoutError
        If the job does not complete within ``max_attempts`` attempts.
    RuntimeError
        If the job fails on the Canva side.
    """
    import asyncio

    async with httpx.AsyncClient() as client:
        for attempt in range(max_attempts):
            response = await client.get(
                f"{CANVA_API_BASE}/autofills/{job_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            response.raise_for_status()
            job = response.json().get("job", response.json())
            status = job.get("status", "")
            if status == "success":
                design_id: str = job["result"]["design"]["id"]
                logger.info("Autofill job succeeded. Design ID: %s", design_id)
                return design_id
            if status == "failed":
                raise RuntimeError(f"Canva autofill job {job_id} failed: {job}")
            logger.debug("Autofill job %s status=%s (attempt %d)", job_id, status, attempt + 1)
            await asyncio.sleep(3)

    raise TimeoutError(f"Canva autofill job {job_id} did not complete after {max_attempts} attempts.")


async def export_design_as_image(
    token: str,
    design_id: str,
    export_format: str = "png",
    max_attempts: int = 20,
) -> bytes:
    """
    Trigger a Canva design export and return the image bytes.

    Parameters
    ----------
    token:
        Valid Canva OAuth2 access token.
    design_id:
        The Canva design to export.
    export_format:
        Image format (``"png"`` or ``"jpg"``).
    max_attempts:
        Maximum polling attempts while waiting for the export to complete.

    Returns
    -------
    bytes
        Raw image data.
    """
    import asyncio

    async with httpx.AsyncClient() as client:
        # Initiate export
        response = await client.post(
            f"{CANVA_API_BASE}/exports",
            json={"design_id": design_id, "format": export_format},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        response.raise_for_status()
        export_data = response.json()
        export_job_id: str = export_data.get("job", {}).get("id") or export_data.get("id", "")
        logger.info("Canva export job created: %s", export_job_id)

        # Poll for completion
        for attempt in range(max_attempts):
            poll_response = await client.get(
                f"{CANVA_API_BASE}/exports/{export_job_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            poll_response.raise_for_status()
            job = poll_response.json().get("job", poll_response.json())
            status = job.get("status", "")
            if status == "success":
                download_url: str = job["urls"][0]
                img_response = await client.get(download_url, timeout=60)
                img_response.raise_for_status()
                logger.info("Design exported successfully.")
                return img_response.content
            if status == "failed":
                raise RuntimeError(f"Canva export job {export_job_id} failed: {job}")
            logger.debug("Export job %s status=%s (attempt %d)", export_job_id, status, attempt + 1)
            await asyncio.sleep(3)

    raise TimeoutError(f"Canva export job {export_job_id} did not complete after {max_attempts} attempts.")
