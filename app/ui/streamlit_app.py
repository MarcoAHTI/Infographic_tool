"""
Streamlit dashboard for the Branded Infographic Orchestrator.

Features
--------
- PDF upload with automatic text extraction.
- "Manual Override" step where the user can edit the structured JSON
  before it is sent to Canva.
- Live "Agent Thought Process" log panel.
- Final infographic image display with download button.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import streamlit as st

# Ensure the project root is on the Python path when running via
# `streamlit run app/ui/streamlit_app.py` from the repo root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env")

from app import brand_config  # noqa: E402
from app.orchestrator import run_pipeline  # noqa: E402
from app.services import canva_service  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Keep pending PKCE pairs persistent across app restarts by storing in a file.
# This ensures OAuth callback still works even if the app restarts.
_PKCE_TTL_SECONDS = 15 * 60
_PKCE_CACHE_FILE = _PROJECT_ROOT / ".pkce_cache"


def _load_pkce_pending() -> Dict[str, tuple[str, float]]:
    """Load PKCE pending states from disk, cleanup expired entries."""
    if not _PKCE_CACHE_FILE.exists():
        return {}
    try:
        import json
        data = json.loads(_PKCE_CACHE_FILE.read_text(encoding="utf-8"))
        # Convert stored format back to tuple
        pending = {k: (v[0], float(v[1])) for k, v in data.items()}
        # Clean up expired entries
        now = time.time()
        pending = {k: v for k, v in pending.items() if now - v[1] <= _PKCE_TTL_SECONDS}
        return pending
    except Exception as e:
        logger.warning(f"Failed to load PKCE cache: {e}")
        return {}


def _save_pkce_pending(pending: Dict[str, tuple[str, float]]) -> None:
    """Save PKCE pending states to disk."""
    try:
        import json
        # Convert tuples to lists for JSON serialization
        data = {k: list(v) for k, v in pending.items()}
        _PKCE_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to save PKCE cache: {e}")


_PKCE_PENDING: Dict[str, tuple[str, float]] = _load_pkce_pending()

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Branded Infographic Orchestrator",
    page_icon="🎨",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Helper: extract text from PDF
# ---------------------------------------------------------------------------

def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract all text from a PDF file's bytes using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(file_bytes))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages_text)


# ---------------------------------------------------------------------------
# Helper: run async pipeline from sync Streamlit context
# ---------------------------------------------------------------------------

def run_async(coro):
    """Run an async coroutine from a synchronous (Streamlit) context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _qp_value(value: Any) -> str:
    """Normalize Streamlit query param values to a single string."""
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def _persist_env_updates(updates: Dict[str, str]) -> None:
    """Persist selected key/value pairs into the project's .env file."""
    env_path = _PROJECT_ROOT / ".env"
    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    remaining = dict(updates)
    new_lines: list[str] = []
    for line in existing_lines:
        if "=" in line and not line.strip().startswith("#"):
            key, _ = line.split("=", 1)
            key = key.strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
                continue
        new_lines.append(line)

    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _extract_code_state_from_callback(callback_url: str) -> tuple[str, str]:
    """Extract OAuth code and state from a callback URL string."""
    parsed = urlparse(callback_url)
    params = parse_qs(parsed.query)
    code = params.get("code", [""])[0]
    state = params.get("state", [""])[0]
    return code, state


def render_canva_auth() -> None:
    """Render Canva OAuth connect flow and keep tokens in process memory."""
    st.header("Step 0 – Connect Canva (OAuth)")

    if "canva_oauth_state" not in st.session_state:
        st.session_state["canva_oauth_state"] = ""
    if "canva_code_verifier" not in st.session_state:
        st.session_state["canva_code_verifier"] = ""

    # ─── Token Status ─────────────────────────────────────────────────
    access_token = os.getenv("CANVA_ACCESS_TOKEN", "").strip()
    refresh_token = os.getenv("CANVA_REFRESH_TOKEN", "").strip()
    
    col1, col2 = st.columns(2)
    with col1:
        if access_token:
            token_preview = access_token[:30] + "…" if len(access_token) > 30 else access_token
            st.success(f"✅ **Access Token**\n`{token_preview}`")
        else:
            st.warning("⚠️ **Access Token**: Not found")
    
    with col2:
        if refresh_token:
            token_preview = refresh_token[:30] + "…" if len(refresh_token) > 30 else refresh_token
            st.success(f"✅ **Refresh Token**\n`{token_preview}`")
        else:
            st.warning("⚠️ **Refresh Token**: Not found")

    redirect_uri = os.getenv("CANVA_REDIRECT_URI", "").strip()
    if redirect_uri:
        st.caption(f"📍 Configured redirect URI: `{redirect_uri}`")
        if "localhost" not in redirect_uri and "127.0.0.1" not in redirect_uri:
            st.warning(
                "Your redirect URI is not local. If this app runs locally, update CANVA_REDIRECT_URI "
                "to http://127.0.0.1:8501/ (and register it in Canva Developer Portal)."
            )

    # ─── Brand Template ID Status ─────────────────────────────────────
    template_id = os.getenv("CANVA_BRAND_TEMPLATE_ID", "").strip()
    if template_id and template_id != "your_brand_template_id_here" and template_id != "PLACEHOLDER_TEMPLATE_ID":
        st.success(f"✅ **Brand Template ID**: `{template_id[:20]}…`")
    else:
        st.error(
            "❌ **Brand Template ID is missing or invalid** — Design creation will fail!\n\n"
            "To find your template ID:\n"
            "1. Go to [Canva Developer Console](https://www.canva.com/developers)\n"
            "2. Find your brand template\n"
            "3. Copy its ID\n"
            "4. Update `.env`: `CANVA_BRAND_TEMPLATE_ID=<your_actual_id>`"
        )

        if "localhost" not in redirect_uri and "127.0.0.1" not in redirect_uri:
            st.warning(
                "Your redirect URI is not local. If this app runs locally, update CANVA_REDIRECT_URI "
                "to http://127.0.0.1:8501/ (and register it in Canva Developer Portal)."
            )

    if st.button("🔐 Generate Canva Authorization URL", use_container_width=True):
        code_verifier, code_challenge = canva_service.generate_pkce_pair()
        state = canva_service.generate_state()
        auth_url = canva_service.build_authorization_url(
            code_challenge=code_challenge,
            state=state,
            redirect_uri=redirect_uri or None,
        )
        st.session_state["canva_code_verifier"] = code_verifier
        st.session_state["canva_oauth_state"] = state
        st.session_state["canva_auth_url"] = auth_url
        _PKCE_PENDING[state] = (code_verifier, time.time())
        _save_pkce_pending(_PKCE_PENDING)  # Persist to disk

    auth_url = st.session_state.get("canva_auth_url")
    if auth_url:
        st.markdown(f"Open this authorization URL: [Authorize in Canva]({auth_url})")

    st.caption("If redirect query params do not return to this page, paste callback URL below.")
    callback_url = st.text_input(
        "Manual callback URL (optional)",
        value="",
        placeholder="https://.../canva_auth?code=...&state=...",
    )

    query_params = st.query_params
    auth_code = _qp_value(query_params.get("code"))
    returned_state = _qp_value(query_params.get("state"))

    if callback_url and (not auth_code or not returned_state):
        manual_code, manual_state = _extract_code_state_from_callback(callback_url)
        auth_code = auth_code or manual_code
        returned_state = returned_state or manual_state

    if auth_code:
        # Drop expired pending states.
        now = time.time()
        expired = [k for k, (_, ts) in _PKCE_PENDING.items() if now - ts > _PKCE_TTL_SECONDS]
        for k in expired:
            _PKCE_PENDING.pop(k, None)
        if expired:
            _save_pkce_pending(_PKCE_PENDING)  # Persist cleanup to disk

        expected_state = st.session_state.get("canva_oauth_state", "")
        if not returned_state:
            st.error("OAuth callback is missing the state parameter. Please retry authorization.")
            return

        # Prefer session verifier if state matches; otherwise fallback to server-side state cache.
        verifier = ""
        session_verifier = st.session_state.get("canva_code_verifier", "")
        if expected_state and returned_state == expected_state and session_verifier:
            verifier = session_verifier
        elif returned_state in _PKCE_PENDING:
            verifier = _PKCE_PENDING[returned_state][0]

        if not verifier:
            st.error("Missing code_verifier in session. Click Generate URL and retry.")
            if st.button("Reset OAuth Callback State", key="reset_oauth_state"):
                st.session_state["canva_oauth_state"] = ""
                st.session_state["canva_code_verifier"] = ""
                st.query_params.clear()
                st.rerun()
            return

        with st.spinner("Exchanging authorization code for tokens…"):
            try:
                token_data = run_async(
                    canva_service.exchange_authorization_code(
                        code=auth_code,
                        code_verifier=verifier,
                        redirect_uri=redirect_uri or None,
                    )
                )
                access_token = token_data.get("access_token", "")
                refresh_token = token_data.get("refresh_token", "")
                expires_in = token_data.get("expires_in")
                canva_service.set_tokens(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=expires_in,
                )
                os.environ["CANVA_ACCESS_TOKEN"] = access_token
                if refresh_token:
                    os.environ["CANVA_REFRESH_TOKEN"] = refresh_token

                to_persist: Dict[str, str] = {"CANVA_ACCESS_TOKEN": access_token}
                if refresh_token:
                    to_persist["CANVA_REFRESH_TOKEN"] = refresh_token
                _persist_env_updates(to_persist)

                _PKCE_PENDING.pop(returned_state, None)
                _save_pkce_pending(_PKCE_PENDING)  # Persist cleanup to disk
                st.session_state["canva_oauth_state"] = ""
                st.session_state["canva_code_verifier"] = ""

                st.success("✅ Canva authorization completed for this app session.")
                if refresh_token:
                    st.info(
                        "Refresh token saved to .env. Future runs should not require re-authorization."
                    )
                st.query_params.clear()
                st.rerun()
            except Exception as exc:
                st.error(f"Canva OAuth exchange failed: {exc}")


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def main() -> None:
    st.title("🎨 Branded Infographic Orchestrator")
    st.caption(
        "Upload a PDF report and let the multi-agent system turn it into a "
        "fully branded infographic."
    )

    render_canva_auth()

    # ── Sidebar: brand settings overview ──────────────────────────────────
    with st.sidebar:
        st.header("🎨 Brand Settings")
        st.write("**Primary colour**")
        st.color_picker("Primary", value=brand_config.COLOR_PRIMARY, disabled=True)
        st.write("**Secondary colour**")
        st.color_picker("Secondary", value=brand_config.COLOR_SECONDARY, disabled=True)
        st.write("**Accent colour**")
        st.color_picker("Accent", value=brand_config.COLOR_ACCENT, disabled=True)
        st.write(f"**Font:** {brand_config.FONT_HEADING}")
        st.write(f"**Logo placement:** {brand_config.LOGO_PLACEMENT}")
        st.divider()
        st.caption("Configure API keys in `.env` (see `.env.example`).")

    # ── Step 1: Upload ─────────────────────────────────────────────────────
    st.header("Step 1 – Upload Document")
    uploaded_file = st.file_uploader(
        "Upload a PDF or plain-text report",
        type=["pdf", "txt"],
        help="The Content Architect agent will extract the key insights from this file.",
    )

    if not uploaded_file:
        st.info("👆 Upload a document to get started.")
        return

    file_bytes = uploaded_file.read()

    if uploaded_file.type == "application/pdf" or uploaded_file.name.endswith(".pdf"):
        with st.spinner("Extracting text from PDF…"):
            document_text = extract_pdf_text(file_bytes)
    else:
        document_text = file_bytes.decode("utf-8", errors="replace")

    st.success(f"✅ Document loaded ({len(document_text):,} characters).")

    with st.expander("Preview extracted text (first 1000 chars)"):
        st.text(document_text[:1000])

    # ── Step 2: Extract content via Agent 1 ───────────────────────────────
    st.header("Step 2 – Content Extraction (Agent 1: Content Architect)")

    if "extracted_content" not in st.session_state:
        st.session_state["extracted_content"] = None

    if st.button("🔍 Extract Structured Content", use_container_width=True):
        with st.spinner("Content Architect is analysing the document…"):
            try:
                from app.agents import content_architect

                content_obj = run_async(content_architect.run(document_text))
                st.session_state["extracted_content"] = content_obj.model_dump()
                st.success("Content extracted successfully!")
            except Exception as exc:
                st.error(f"Extraction failed: {exc}")
                return

    if not st.session_state["extracted_content"]:
        return

    # ── Step 3: Manual Override ────────────────────────────────────────────
    st.header("Step 3 – Manual Override (Optional)")
    st.info(
        "Review and edit the structured JSON below before it is sent to Canva. "
        "Changes here override the agent's output."
    )

    raw_json = json.dumps(st.session_state["extracted_content"], indent=2)
    edited_json_str = st.text_area(
        "Structured Content JSON",
        value=raw_json,
        height=300,
        help="Edit headline, data_points, or visual_metaphor as needed.",
    )

    try:
        content_to_use: Dict[str, Any] = json.loads(edited_json_str)
        st.success("✅ JSON is valid.")
    except json.JSONDecodeError as exc:
        st.error(f"Invalid JSON: {exc}")
        return

    # ── Step 4: Generate Infographic ──────────────────────────────────────
    st.header("Step 4 – Generate Branded Infographic")

    # Determine whether the user changed the JSON
    override = (
        content_to_use
        if content_to_use != st.session_state["extracted_content"]
        else None
    )

    if st.button("🚀 Generate Infographic", type="primary", use_container_width=True):
        log_placeholder = st.empty()
        progress_bar = st.progress(0)

        with st.spinner("Multi-agent pipeline running…"):
            try:
                final_state = run_async(
                    run_pipeline(
                        document_text=document_text,
                        # Always pass the user's version (edited or original)
                        content_override=content_to_use,
                    )
                )
            except Exception as exc:
                st.error(f"Pipeline error: {exc}")
                return

        progress_bar.progress(100)

        # ── Agent Thought Process log ──────────────────────────────────
        st.subheader("🤖 Agent Thought Process")
        thought_log = final_state.get("log", [])
        with st.expander("View agent logs", expanded=True):
            for entry in thought_log:
                st.write(entry)

        # ── QA Result ─────────────────────────────────────────────────
        qa = final_state.get("qa_result")
        if qa:
            st.subheader("🔎 Brand QA Result")
            col1, col2, col3 = st.columns(3)
            col1.metric("Logo Visible", "✅" if qa.get("logo_visible") else "❌")
            col2.metric("Colours Correct", "✅" if qa.get("colors_correct") else "❌")
            col3.metric("No Text Overlap", "✅" if qa.get("no_text_overlap") else "❌")
            if qa.get("feedback"):
                st.info(f"Feedback: {qa['feedback']}")

        # ── Final image ────────────────────────────────────────────────
        image_bytes: Optional[bytes] = final_state.get("final_image_bytes")
        if image_bytes:
            st.subheader("🖼️ Generated Infographic")
            st.image(image_bytes, use_column_width=True)
            st.download_button(
                label="⬇️ Download Infographic (PNG)",
                data=image_bytes,
                file_name="branded_infographic.png",
                mime="image/png",
                use_container_width=True,
            )
        else:
            error_msg = final_state.get("error", "Unknown error — no image was produced.")
            st.error(f"❌ Infographic generation failed: {error_msg}")


if __name__ == "__main__":
    main()
