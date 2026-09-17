"""Text AI providers for explanation generation (server-side only).

``TEXT_AI_PROVIDER`` selects the backend; API clients never learn which one:

- ``ollama`` (default, development): local Ollama ``/api/chat`` at OLLAMA_BASE_URL.
- ``omniroute`` (hosted): an OmniRoute gateway's OpenAI-compatible
  ``/chat/completions`` at OMNIROUTE_BASE_URL (e.g. ``https://host/v1``) with
  OMNIROUTE_API_KEY as a bearer token.

Providers only receive text prompts built by the backend from structured model
output; they never receive images. Credentials are never logged.
"""
import json
import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import httpx

from ... import config

logger = logging.getLogger(__name__)

MAX_COMPLETION_CHARS = 20_000


class TextAIUnavailable(RuntimeError):
    """The configured text provider could not produce a completion."""


@dataclass
class Completion:
    text: str
    model: str


class TextAIProvider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int,
                      temperature: float) -> Completion:
        ...


def _post(url: str, payload: dict, headers: Optional[dict] = None) -> dict:
    try:
        with httpx.Client(timeout=config.TEXT_AI_TIMEOUT_SECONDS, follow_redirects=False) as client:
            resp = client.post(url, json=payload, headers=headers or {})
    except httpx.TimeoutException as exc:
        raise TextAIUnavailable("Text AI request timed out") from exc
    except httpx.HTTPError as exc:
        raise TextAIUnavailable(f"Text AI service unreachable ({type(exc).__name__})") from exc
    if resp.status_code != 200:
        raise TextAIUnavailable(f"Text AI service returned HTTP {resp.status_code}")
    if len(resp.content) > 4 * MAX_COMPLETION_CHARS + 65536:
        raise TextAIUnavailable("Text AI response too large")
    try:
        return resp.json()
    except ValueError as exc:
        raise TextAIUnavailable("Text AI response is not JSON") from exc


class OllamaTextProvider:
    name = "ollama"

    def __init__(self):
        self.base = (config.OLLAMA_BASE_URL or "http://localhost:11434").rstrip("/")
        self.model = config.OLLAMA_MODEL or "qwen3:8b"

    def complete_json(self, system, user, schema, max_tokens, temperature):
        body = _post(f"{self.base}/api/chat", {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "think": False,
            "keep_alive": "30m",  # keep the model loaded between explanations
            "options": {"temperature": temperature, "num_predict": max_tokens},
        })
        text = ((body.get("message") or {}).get("content") or "") if isinstance(body, dict) else ""
        return Completion(text=text[:MAX_COMPLETION_CHARS], model=self.model)


class OmniRouteTextProvider:
    name = "omniroute"

    def __init__(self):
        self.base = (config.OMNIROUTE_BASE_URL or "").rstrip("/")
        self.key = (config.OMNIROUTE_API_KEY or "").strip()
        self.model = (config.OMNIROUTE_MODEL or "").strip()
        if not (self.base and self.key and self.model):
            raise TextAIUnavailable("OmniRoute text provider is not configured")
        if not self.base.startswith("https://") and not self.base.startswith(("http://localhost", "http://127.0.0.1")):
            raise TextAIUnavailable("OmniRoute base URL must use HTTPS")

    def complete_json(self, system, user, schema, max_tokens, temperature):
        body = _post(f"{self.base}/chat/completions", {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user + "\n\nRespond with one JSON object matching this JSON schema:\n"
                 + json.dumps(schema)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }, headers={"Authorization": f"Bearer {self.key}"})
        try:
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            text = ""
        return Completion(text=str(text)[:MAX_COMPLETION_CHARS], model=self.model)


_PROVIDERS = {"ollama": OllamaTextProvider, "omniroute": OmniRouteTextProvider}


def get_text_ai_provider() -> TextAIProvider:
    key = (config.TEXT_AI_PROVIDER or "ollama").strip().lower()
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise TextAIUnavailable("Unknown TEXT_AI_PROVIDER value")
    return cls()
