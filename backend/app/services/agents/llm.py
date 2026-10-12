"""The local language model (Ollama). Structured output only: the model must answer in the given JSON schema."""

import json
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("leadfinder.agents")


def available() -> bool:
    """The Ollama server is up and has the configured model."""
    s = get_settings()
    try:
        tags = httpx.get(f"{s.ollama_url}/api/tags", timeout=5).json()
    except (httpx.HTTPError, ValueError):
        return False
    return any(m.get("name") == s.ollama_model or m.get("model") == s.ollama_model for m in tags.get("models", []))


def chat_json(system: str, user: str, schema: dict) -> dict | None:
    """One answer as a dict matching `schema`, or None when the model is unreachable or answers nonsense."""
    s = get_settings()
    try:
        r = httpx.post(f"{s.ollama_url}/api/chat", timeout=s.ollama_timeout_seconds, json={
            "model": s.ollama_model, "stream": False, "format": schema,
            "options": {"temperature": 0.2, "num_ctx": 4096},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
        r.raise_for_status()
        return json.loads(r.json()["message"]["content"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("model call failed: %s", exc)
        return None
