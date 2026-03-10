"""
Brand Critic Agent (Agent 3).

Responsibilities
----------------
- Accept the exported infographic image bytes.
- Send the image to Gemini Vision for quality assurance.
- Check: logo visibility, colour correctness, and text-overlap absence.
- Return a validated :class:`~app.models.QAResult` model.
- If QA fails, signal the orchestrator to re-run the Design Liaison.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app import brand_config
from app.models import QAResult
from app.services import gemini_service

logger = logging.getLogger(__name__)

QA_PROMPT_TEMPLATE = """
You are a meticulous brand quality-assurance inspector reviewing an infographic image.

Evaluate the image against the following brand standards:
- Brand colours (hex): primary={color_primary}, secondary={color_secondary}, accent={color_accent}
- Logo must be visible and positioned at the {logo_placement} corner.
- No text elements should overlap each other.

Return your analysis as a **single valid JSON object** with exactly these keys:
{{
  "logo_visible": true | false,
  "colors_correct": true | false,
  "no_text_overlap": true | false,
  "passed": true | false,
  "feedback": "<A concise sentence explaining any issues found, or 'All checks passed.' if OK>"
}}

"passed" should be true only when ALL three checks (logo_visible, colors_correct, no_text_overlap) are true.
"""


async def run(image_bytes: bytes) -> QAResult:
    """
    Perform brand QA on the infographic image using Gemini Vision.

    Parameters
    ----------
    image_bytes:
        Raw bytes of the exported infographic PNG/JPG.

    Returns
    -------
    QAResult
        Structured QA result including individual check flags and a feedback message.
    """
    logger.info("[BrandCritic] Running brand QA on exported image (%d bytes)…", len(image_bytes))

    prompt = QA_PROMPT_TEMPLATE.format(
        color_primary=brand_config.COLOR_PRIMARY,
        color_secondary=brand_config.COLOR_SECONDARY,
        color_accent=brand_config.COLOR_ACCENT,
        logo_placement=brand_config.LOGO_PLACEMENT,
    )

    raw: Dict[str, Any] = await gemini_service.analyze_image_json(
        image_bytes=image_bytes,
        prompt=prompt,
        mime_type="image/png",
    )

    result = QAResult(**raw)
    if result.passed:
        logger.info("[BrandCritic] QA passed. ✓")
    else:
        logger.warning("[BrandCritic] QA failed: %s", result.feedback)

    return result
