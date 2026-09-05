from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import get_settings


class LLMError(RuntimeError):
    pass


async def generate_json(system: str, user: str, temperature: float = 0.2) -> dict[str, Any]:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not configured.")

    url = (
        f"{settings.gemini_base_url.rstrip('/')}/models/{settings.gemini_model}:generateContent"
        f"?key={settings.gemini_api_key}"
    )
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
        },
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(url, json=body)
        if response.status_code >= 400:
            raise LLMError(f"Gemini error {response.status_code}: {response.text[:800]}")
        data = response.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected Gemini payload: {data}") from exc
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise LLMError("Gemini did not return a JSON object.")
    return parsed
