"""
Async wrapper around the Canva Connect API (2026 Edition).

Covers:
  - OAuth2 client-credentials token retrieval.
  - Template search by brand_template_id.
  - Design creation via the Autofill / Design Editing endpoint.
  - Export polling and image download.

All network calls use ``httpx.AsyncClient`` so that the entire orchestration
pipeline can remain non-blocking.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canva API base URL
# ---------------------------------------------------------------------------
CANVA_API_BASE = "https://api.canva.com/rest/v1"
CANVA_AUTH_URL = "https://api.canva.com/rest/v1/oauth/token"


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
    client_id, client_secret = _get_credentials()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            CANVA_AUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "design:content:write design:content:read asset:read",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["access_token"]


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
