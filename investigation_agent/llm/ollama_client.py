"""Local Ollama HTTP API client with retries and timeouts."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from investigation_agent.config import ollama_base_url, ollama_model, ollama_timeout_seconds

logger = logging.getLogger(__name__)


class OllamaChatError(RuntimeError):
    """Raised when Ollama returns an error or is unreachable."""


def chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_retries: int = 3,
) -> str:
    """
    Call Ollama /api/chat (non-streaming) and return assistant message content.
    """
    base = ollama_base_url().rstrip("/")
    model = ollama_model()
    timeout = ollama_timeout_seconds()
    url = f"{base}/api/chat"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(url, json=payload)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500] if e.response else ""
            last_err = OllamaChatError(f"Ollama HTTP {e.response.status_code}: {body}")
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError) as e:
            last_err = OllamaChatError(
                f"Cannot reach Ollama at {base}. Is `ollama serve` running? ({e})"
            )
        except json.JSONDecodeError as e:
            last_err = OllamaChatError(f"Invalid JSON from Ollama: {e}")
        else:
            msg = data.get("message") or {}
            content = msg.get("content")
            if content is None:
                last_err = OllamaChatError(f"Unexpected Ollama response: {data!r}")
            else:
                return str(content).strip()

        if attempt < max_retries - 1:
            delay = 1.0 * (2**attempt)
            logger.warning("Ollama request failed (attempt %s/%s), retrying in %ss", attempt + 1, max_retries, delay)
            time.sleep(delay)

    raise last_err if last_err else OllamaChatError("Unknown Ollama error")
