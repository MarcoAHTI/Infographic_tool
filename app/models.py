"""Pydantic models shared across agents."""
from __future__ import annotations

from typing import List
from pydantic import BaseModel, Field


class InfographicContent(BaseModel):
    """Structured content extracted by the Content Architect agent."""

    headline: str = Field(
        ...,
        description="A punchy, attention-grabbing title for the infographic.",
    )
    data_points: List[str] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="List of up to 5 key insights (max 20 words each).",
    )
    visual_metaphor: str = Field(
        ...,
        description="A short description of an icon or illustration that represents the topic.",
    )


class QAResult(BaseModel):
    """Result returned by the Brand Critic agent."""

    logo_visible: bool
    colors_correct: bool
    no_text_overlap: bool
    passed: bool
    feedback: str
