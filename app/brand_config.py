"""
Brand configuration for the Branded Infographic Orchestrator.
Centralises all brand-specific settings: colours, fonts, and layout rules.
"""

# ---------------------------------------------------------------------------
# Brand colours (hex)
# ---------------------------------------------------------------------------
BRAND_COLORS = {
    "primary": "#336A88",
    "secondary": "#009DDC",
    "accent": "#EE3124",
}

# Convenience aliases
COLOR_PRIMARY = BRAND_COLORS["primary"]
COLOR_SECONDARY = BRAND_COLORS["secondary"]
COLOR_ACCENT = BRAND_COLORS["accent"]

# ---------------------------------------------------------------------------
# Brand fonts
# ---------------------------------------------------------------------------
BRAND_FONTS = {
    "heading": "Ahti Sans",
    "body": "Ahti Sans",
}

FONT_HEADING = BRAND_FONTS["heading"]
FONT_BODY = BRAND_FONTS["body"]

# ---------------------------------------------------------------------------
# Logo placement
# ---------------------------------------------------------------------------
LOGO_PLACEMENT = "bottom-right"

# ---------------------------------------------------------------------------
# Canva template / brand kit identifiers (placeholders – set via .env)
# ---------------------------------------------------------------------------
import os  # noqa: E402

CANVA_BRAND_TEMPLATE_ID: str = os.getenv("CANVA_BRAND_TEMPLATE_ID", "PLACEHOLDER_TEMPLATE_ID")

# ---------------------------------------------------------------------------
# QA thresholds used by the Brand Critic agent
# ---------------------------------------------------------------------------
MAX_DESIGN_RETRIES = 3
