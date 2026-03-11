"""
Async wrapper around the Mistral AI API.

Supports:
  - Text generation from a prompt string.
  - Structured JSON extraction (used by Content Architect).
  - Vision-based analysis of an image URL or bytes (used by Brand Critic).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any, Dict, Optional

from mistralai.client import Mistral

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model identifiers (configurable via environment variables)
# ---------------------------------------------------------------------------
TEXT_MODEL = os.getenv("MISTRAL_TEXT_MODEL", "mistral-large-latest")
VISION_MODEL = os.getenv("MISTRAL_VISION_MODEL", "pixtral-12b-2409")

# ---------------------------------------------------------------------------
# Retry settings for rate-limit errors
# ---------------------------------------------------------------------------
MAX_RETRIES = int(os.getenv("MISTRAL_MAX_RETRIES", "3"))
RETRY_BASE_DELAY = float(os.getenv("MISTRAL_RETRY_DELAY", "15"))  # seconds


def _get_client() -> Mistral:
    """Get or create the Mistral API client."""
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "MISTRAL_API_KEY is not set. Add it to your .env file or environment."
        )
    return Mistral(api_key=api_key)


async def _call_with_retry(fn, *args, **kwargs):
    """Call *fn* with automatic retry on rate-limit errors."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if ("429" in str(exc) or "rate" in str(exc).lower()) and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * attempt
                logger.warning(
                    "Rate-limited. Retrying in %.0fs (attempt %d/%d)…",
                    delay, attempt, MAX_RETRIES,
                )
                await asyncio.sleep(delay)
            else:
                raise


async def generate_text(prompt: str, temperature: float = 0.4) -> str:
    """
    Generate a text response from Mistral.

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
    client = _get_client()

    def _call():
        response = client.chat.complete(
            model=TEXT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return response.choices[0].message.content

    return await _call_with_retry(_call)


async def extract_structured_json(
    prompt: str,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """
    Ask Mistral to return a JSON object and parse the response.

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
    client = _get_client()

    def _call():
        response = client.chat.complete(
            model=TEXT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return response.choices[0].message.content

    text = await _call_with_retry(_call)
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Mistral returned non-JSON output: {text!r}") from exc


async def analyze_image(
    image_bytes: bytes,
    prompt: str,
    mime_type: str = "image/png",
    temperature: float = 0.2,
) -> str:
    """
    Send an image to Mistral Vision and return the model's textual analysis.

    Parameters
    ----------
    image_bytes:
        Raw bytes of the image to analyse.
    prompt:
        Instruction for the vision model (e.g., QA checklist questions).
    mime_type:
        MIME type of the image (e.g., "image/png", "image/jpeg").
    temperature:
        Sampling temperature.

    Returns
    -------
    str
        The model's description / analysis of the image.
    """
    client = _get_client()

    # Encode image as base64
    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    def _call():
        response = client.chat.complete(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}"
                            },
                        },
                    ],
                }
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content

    return await _call_with_retry(_call)


async def analyze_image_json(
    image_bytes: bytes,
    prompt: str,
    mime_type: str = "image/png",
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """
    Send an image to Mistral Vision and parse the JSON response.

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
    client = _get_client()

    # Encode image as base64
    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    def _call():
        response = client.chat.complete(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}"
                            },
                        },
                    ],
                }
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content

    text = await _call_with_retry(_call)
    text = text.strip()

    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Mistral Vision returned non-JSON output: {text!r}") from exc
