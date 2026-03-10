"""
Multi-agent orchestration using LangGraph.

Pipeline
--------
1. **extract_content** – Content Architect agent reads the document and produces
   structured JSON content.
2. **human_override** – Optional pause where the Streamlit UI (or a caller) can
   mutate the JSON before it reaches Canva.
3. **create_design** – Design Liaison agent submits the content to Canva and
   retrieves the exported image bytes.
4. **qa_design** – Brand Critic agent inspects the image and returns a QAResult.
5. **check_qa** – Router: if QA passed → END; if failed and retries remain →
   back to **create_design**; otherwise → END with failure status.

State
-----
All inter-node state is carried in a typed :class:`OrchestratorState` dict that
LangGraph threads through the graph automatically.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from app import brand_config
from app.agents import brand_critic, content_architect, design_liaison
from app.models import InfographicContent, QAResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared state schema
# ---------------------------------------------------------------------------

class OrchestratorState(TypedDict, total=False):
    """Typed state object passed between LangGraph nodes."""

    # Input
    document_text: str

    # Intermediate
    content: Optional[Dict[str, Any]]        # InfographicContent as dict
    image_bytes: Optional[bytes]             # Exported PNG bytes
    qa_result: Optional[Dict[str, Any]]      # QAResult as dict
    retry_count: int
    log: List[str]                           # Human-readable thought process

    # Output
    final_image_bytes: Optional[bytes]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _log(state: OrchestratorState, message: str) -> None:
    state.setdefault("log", []).append(message)
    logger.info(message)


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------

async def node_extract_content(state: OrchestratorState) -> OrchestratorState:
    """Agent 1 – Content Architect."""
    _log(state, "🔍 [Content Architect] Analysing document and extracting structured content…")
    try:
        content: InfographicContent = await content_architect.run(state["document_text"])
        state["content"] = content.model_dump()
        _log(state, f"✅ [Content Architect] Headline: \"{content.headline}\"")
    except (ValueError, KeyError, httpx.HTTPError, TimeoutError) as exc:
        state["error"] = f"Content extraction failed: {exc}"
        _log(state, f"❌ [Content Architect] Error: {exc}")
    return state


async def node_create_design(state: OrchestratorState) -> OrchestratorState:
    """Agent 2 – Design Liaison."""
    _log(
        state,
        f"🎨 [Design Liaison] Creating branded design "
        f"(attempt {state.get('retry_count', 0) + 1}/{brand_config.MAX_DESIGN_RETRIES})…",
    )
    try:
        content = InfographicContent(**state["content"])
        image_bytes = await design_liaison.run(content)
        state["image_bytes"] = image_bytes
        _log(state, f"✅ [Design Liaison] Design exported ({len(image_bytes):,} bytes).")
    except (ValueError, KeyError, httpx.HTTPError, TimeoutError, RuntimeError) as exc:
        state["error"] = f"Design creation failed: {exc}"
        _log(state, f"❌ [Design Liaison] Error: {exc}")
    return state


async def node_qa_design(state: OrchestratorState) -> OrchestratorState:
    """Agent 3 – Brand Critic."""
    _log(state, "🔎 [Brand Critic] Running brand quality-assurance check…")
    if not state.get("image_bytes"):
        state["qa_result"] = {
            "logo_visible": False,
            "colors_correct": False,
            "no_text_overlap": False,
            "passed": False,
            "feedback": "No image bytes available to inspect.",
        }
        return state

    try:
        qa: QAResult = await brand_critic.run(state["image_bytes"])
        state["qa_result"] = qa.model_dump()
        if qa.passed:
            state["final_image_bytes"] = state["image_bytes"]
            _log(state, "✅ [Brand Critic] All quality checks passed!")
        else:
            _log(state, f"⚠️  [Brand Critic] QA failed – {qa.feedback}")
    except (ValueError, httpx.HTTPError, TimeoutError) as exc:
        state["error"] = f"QA check failed: {exc}"
        _log(state, f"❌ [Brand Critic] Error: {exc}")
    return state


def node_check_qa(state: OrchestratorState) -> str:
    """
    Router node – decides the next graph step based on QA result.

    Returns
    -------
    str
        One of: ``"end"``, ``"retry"``.
    """
    qa = state.get("qa_result") or {}
    retry_count = state.get("retry_count", 0)

    if qa.get("passed") or state.get("final_image_bytes"):
        return "end"

    if retry_count < brand_config.MAX_DESIGN_RETRIES - 1:
        state["retry_count"] = retry_count + 1
        _log(state, f"🔄 Retrying design creation (attempt {state['retry_count'] + 1})…")
        return "retry"

    _log(state, "🛑 Max retries reached. Returning best available image.")
    state["final_image_bytes"] = state.get("image_bytes")
    return "end"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Build and compile the LangGraph orchestration graph."""
    graph = StateGraph(OrchestratorState)

    graph.add_node("extract_content", node_extract_content)
    graph.add_node("create_design", node_create_design)
    graph.add_node("qa_design", node_qa_design)

    graph.set_entry_point("extract_content")
    graph.add_edge("extract_content", "create_design")
    graph.add_edge("create_design", "qa_design")
    graph.add_conditional_edges(
        "qa_design",
        node_check_qa,
        {"end": END, "retry": "create_design"},
    )

    return graph.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_pipeline(
    document_text: str,
    content_override: Optional[Dict[str, Any]] = None,
) -> OrchestratorState:
    """
    Execute the full orchestration pipeline.

    Parameters
    ----------
    document_text:
        Raw text extracted from the uploaded PDF.
    content_override:
        Optional pre-edited content dict that replaces the Content Architect
        output (used by the "Manual Override" UI step).

    Returns
    -------
    OrchestratorState
        Final state containing ``final_image_bytes``, ``log``, ``qa_result``,
        and any ``error`` messages.
    """
    app_graph = build_graph()

    initial_state: OrchestratorState = {
        "document_text": document_text,
        "retry_count": 0,
        "log": [],
    }

    if content_override:
        # Skip Agent 1 by pre-populating content
        initial_state["content"] = content_override
        logger.info("Manual content override applied; skipping Content Architect.")

        # Build a trimmed graph that starts from create_design
        override_graph = StateGraph(OrchestratorState)
        override_graph.add_node("create_design", node_create_design)
        override_graph.add_node("qa_design", node_qa_design)
        override_graph.set_entry_point("create_design")
        override_graph.add_edge("create_design", "qa_design")
        override_graph.add_conditional_edges(
            "qa_design",
            node_check_qa,
            {"end": END, "retry": "create_design"},
        )
        compiled = override_graph.compile()
        final_state = await compiled.ainvoke(initial_state)
    else:
        final_state = await app_graph.ainvoke(initial_state)

    return final_state
