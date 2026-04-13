"""Minimal ReAct loop (no external agent framework)."""

from __future__ import annotations

import json
import re
from typing import Any

from investigation_agent.agent.prompts import AGENT_SYSTEM
from investigation_agent.agent.tools import InvestigationTools
from investigation_agent.llm.ollama_client import OllamaChatError, chat_completion


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def run_react(
    tools: InvestigationTools,
    user_query: str,
    *,
    max_turns: int = 6,
) -> str:
    """
    Run a short tool-using loop. Returns final assistant text or error message.
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": AGENT_SYSTEM},
        {
            "role": "user",
            "content": user_query
            + "\n\nReply with exactly one JSON object: "
            '{"action":"tool","name":"...","args":{...}} or {"action":"final","answer":"..."}',
        },
    ]

    for _ in range(max_turns):
        try:
            raw = chat_completion(messages, temperature=0.1)
        except OllamaChatError as e:
            return f"Ollama error: {e}"

        data = _extract_json_object(raw)
        if not data:
            return f"Model did not return valid JSON. Raw:\n{raw[:2000]}"

        action = data.get("action")
        if action == "final":
            return str(data.get("answer") or "").strip() or "(empty answer)"

        if action == "tool":
            name = str(data.get("name") or "")
            args = data.get("args") if isinstance(data.get("args"), dict) else {}
            observation = tools.dispatch(name, args)
            if len(observation) > 12000:
                observation = observation[:12000] + "\n[...truncated...]"
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": "Tool result:\n"
                    + observation
                    + '\n\nContinue: one JSON object only: {"action":"tool",...} or {"action":"final",...}',
                },
            )
            continue

        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": 'Invalid action. Reply with one JSON: {"action":"final","answer":"..."}',
            }
        )

    return "Max turns reached without a final answer."
