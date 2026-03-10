"""
Content Architect Agent (Agent 1).

Responsibilities
----------------
- Accept raw document text (extracted from a PDF by the caller).
- Call the Gemini text API with a structured-extraction prompt.
- Return a validated :class:`~app.models.InfographicContent` Pydantic model.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.models import InfographicContent
from app.services import gemini_service

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_TEMPLATE = """
You are an expert content strategist who creates engaging infographics.

Given the following document text, extract exactly the following information and
return it as a **single valid JSON object** — no markdown, no explanation:

{{
  "headline": "<A punchy, attention-grabbing title for the infographic (max 10 words)>",
  "data_points": [
    "<Key insight 1 (max 20 words)>",
    "<Key insight 2 (max 20 words)>",
    "<Key insight 3 (max 20 words)>",
    "<Key insight 4 (max 20 words)>",
    "<Key insight 5 (max 20 words)>"
  ],
  "visual_metaphor": "<A short description of an icon or illustration that best represents the central theme>"
}}

Rules:
- The headline must be punchy and under 10 words.
- Provide exactly 5 data_points, each no longer than 20 words.
- The visual_metaphor should describe a concrete visual (e.g. "A rocket launching upward symbolising rapid growth").

Document text:
---
{document_text}
---
"""


async def run(document_text: str) -> InfographicContent:
    """
    Extract structured infographic content from raw document text.

    Parameters
    ----------
    document_text:
        The full text of the source document.

    Returns
    -------
    InfographicContent
        Validated Pydantic model with headline, data_points, and visual_metaphor.

    Raises
    ------
    ValueError
        If the Gemini response cannot be parsed or validated.
    """
    logger.info("[ContentArchitect] Extracting structured content from document…")
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(document_text=document_text[:12000])

    raw: Dict[str, Any] = await gemini_service.extract_structured_json(prompt)

    # Validate and coerce via Pydantic
    content = InfographicContent(**raw)
    logger.info("[ContentArchitect] Extraction complete. Headline: %r", content.headline)
    return content
