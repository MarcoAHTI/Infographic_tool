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
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

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

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

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


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def main() -> None:
    st.title("🎨 Branded Infographic Orchestrator")
    st.caption(
        "Upload a PDF report and let the multi-agent system turn it into a "
        "fully branded infographic."
    )

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
