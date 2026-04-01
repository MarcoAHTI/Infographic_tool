"""
Design Liaison Agent (Agent 2).

Responsibilities
----------------
- Accept a validated :class:`~app.models.InfographicContent` payload.
- Authenticate with the Canva Connect API.
- Create a design by autofilling the brand template with the content.
- Enforce brand colours, fonts, and logo placement.
- Return the exported infographic as raw image bytes.
"""
from __future__ import annotations

import logging
import os

from app import brand_config
from app.models import InfographicContent
from app.services import canva_service

logger = logging.getLogger(__name__)


async def run(content: InfographicContent) -> bytes:
    """
    Produce a branded infographic image from the provided content.

    Parameters
    ----------
    content:
        Validated content extracted by the Content Architect agent.

    Returns
    -------
    bytes
        PNG image data of the generated infographic.
    """
    logger.info("[DesignLiaison] Starting design generation")
    
    # Validate brand template ID early
    template_id = brand_config.CANVA_BRAND_TEMPLATE_ID
    if not template_id or template_id in ("PLACEHOLDER_TEMPLATE_ID", "your_brand_template_id_here"):
        msg = (
            f"[DesignLiaison] ❌ Brand template ID is invalid or placeholder: '{template_id}'\n"
            "Set CANVA_BRAND_TEMPLATE_ID in .env to your actual Canva template ID."
        )
        logger.error(msg)
        raise ValueError(msg)
    
    logger.info("[DesignLiaison] Authenticating with Canva Connect API…")
    try:
        token = await canva_service.get_access_token()
        logger.info("[DesignLiaison] Authentication successful (token length: %d)", len(token))
    except Exception as e:
        logger.error("[DesignLiaison] Authentication failed: %s", str(e))
        raise

    logger.info("[DesignLiaison] Using brand template: %s", template_id)

    content_dict = content.model_dump()
    logger.info(
        "[DesignLiaison] Content summary: headline='%s', %d data points, metaphor='%s'",
        content_dict.get("headline", "")[:50],
        len(content_dict.get("data_points", [])),
        content_dict.get("visual_metaphor", "")[:50],
    )

    logger.info("[DesignLiaison] Submitting autofill job to Canva…")
    try:
        job_id = await canva_service.create_design_from_template(
            token=token,
            brand_template_id=template_id,
            content=content_dict,
            brand_colors=brand_config.BRAND_COLORS,
            brand_font=brand_config.FONT_HEADING,
            logo_placement=brand_config.LOGO_PLACEMENT,
        )
        logger.info("[DesignLiaison] Autofill job created: %s", job_id)
    except Exception as e:
        logger.error("[DesignLiaison] Autofill submission failed: %s", str(e))
        raise

    logger.info("[DesignLiaison] Polling autofill job: %s", job_id)
    design_id = await canva_service.poll_autofill_job(token, job_id)
    logger.info("[DesignLiaison] Autofill complete, design ID: %s", design_id)

    logger.info("[DesignLiaison] Exporting design %s as PNG…", design_id)
    image_bytes = await canva_service.export_design_as_image(token, design_id)

    logger.info("[DesignLiaison] Export complete (%d bytes).", len(image_bytes))
    return image_bytes
