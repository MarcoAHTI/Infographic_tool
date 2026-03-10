"""
Async wrapper around the Google Gemini API.

Supports:
  - Text generation from a prompt string.
  - Structured JSON extraction (used by Content Architect).
  - Vision-based analysis of an image URL or bytes (used by Brand Critic).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import google.generativeai as genai
from google.generativeai.types import GenerationConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model identifiers (configurable via environment variables)
# ---------------------------------------------------------------------------
TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.0-flash")


def _get_client() -> None:
    """Configure the Gemini SDK with the API key from the environment."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY is not set. Add it to your .env file or environment."
        )
    genai.configure(api_key=api_key)


async def generate_text(prompt: str, temperature: float = 0.4) -> str:
    """
    Generate a text response from Gemini.

    Parameters
    ----------
    prompt:
        The full prompt to send to the model.
    temperature:
        Sampling temperature (lower = more deterministic).

    Returns
    -------
    str
        The model's text response.
    """
    _get_client()
    model = genai.GenerativeModel(TEXT_MODEL)
    response = model.generate_content(
        prompt,
        generation_config=GenerationConfig(temperature=temperature),
    )
    return response.text


async def extract_structured_json(
    prompt: str,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """
    Ask Gemini to return a JSON object and parse the response.

    The prompt should instruct the model to respond **only** with valid JSON.

    Parameters
    ----------
    prompt:
        Prompt that includes a JSON schema description.
    temperature:
        Low temperature for deterministic structured output.

    Returns
    -------
    dict
        Parsed JSON dictionary from the model response.

    Raises
    ------
    ValueError
        If the model response cannot be parsed as JSON.
    """
    _get_client()
    model = genai.GenerativeModel(TEXT_MODEL)
    response = model.generate_content(
        prompt,
        generation_config=GenerationConfig(
            temperature=temperature,
            response_mime_type="application/json",
        ),
    )
    text = response.text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned non-JSON output: {text!r}") from exc


async def analyze_image(
    image_bytes: bytes,
    prompt: str,
    mime_type: str = "image/png",
    temperature: float = 0.2,
) -> str:
    """
    Send an image to Gemini Vision and return the model's textual analysis.

    Parameters
    ----------
    image_bytes:
        Raw bytes of the image to analyse.
    prompt:
        Instruction for the vision model (e.g., QA checklist questions).
    mime_type:
        MIME type of the image.
    temperature:
        Sampling temperature.

    Returns
    -------
    str
        The model's description / analysis of the image.
    """
    _get_client()
    model = genai.GenerativeModel(VISION_MODEL)
    image_part = {"mime_type": mime_type, "data": image_bytes}
    response = model.generate_content(
        [prompt, image_part],
        generation_config=GenerationConfig(temperature=temperature),
    )
    return response.text


async def analyze_image_json(
    image_bytes: bytes,
    prompt: str,
    mime_type: str = "image/png",
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """
    Send an image to Gemini Vision and parse the JSON response.

    Parameters
    ----------
    image_bytes:
        Raw bytes of the image to analyse.
    prompt:
        Instruction for the vision model; must request JSON output.
    mime_type:
        MIME type of the image.
    temperature:
        Sampling temperature.

    Returns
    -------
    dict
        Parsed JSON from the model.
    """
    _get_client()
    model = genai.GenerativeModel(VISION_MODEL)
    image_part = {"mime_type": mime_type, "data": image_bytes}
    response = model.generate_content(
        [prompt, image_part],
        generation_config=GenerationConfig(
            temperature=temperature,
            response_mime_type="application/json",
        ),
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini Vision returned non-JSON output: {text!r}") from exc
