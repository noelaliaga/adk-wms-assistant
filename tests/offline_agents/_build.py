from __future__ import annotations

import os
import re
from enum import StrEnum
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.evaluation.eval_set import EvalSet
from google.genai import types

from fakes import ScriptedLlm, call, say
from wms_assistant.config import Settings
from wms_assistant.factory import build_agent

EVALSET = Path(__file__).resolve().parents[2] / "evals" / "wms_assistant.test.json"


class Mode(StrEnum):
    REPLAY = "replay"
    SKIP_TOOLS = "skip_tools"
    GUESSES = "guesses"
    EXTRA_TOOLS = "extra_tools"


def _without_questions(text: str) -> str:
    """Drop every sentence that ends in '?' and state an assumption instead."""
    kept = [s for s in re.split(r"(?<=[.?!])\s+", text) if not s.endswith("?")]
    return " ".join([*kept, "I assumed the first match."])


def _scripts(mode: Mode) -> dict[str, list[types.Content]]:
    eval_set = EvalSet.model_validate_json(EVALSET.read_text(encoding="utf-8"))
    scripts: dict[str, list[types.Content]] = {}
    for case in eval_set.eval_cases:
        for invocation in case.conversation or []:
            user = "".join(p.text or "" for p in invocation.user_content.parts or [])
            turns: list[types.Content] = []
            data = invocation.intermediate_data
            tool_uses = (
                list(data.tool_uses) if data is not None and hasattr(data, "tool_uses") else []
            )
            if mode is not Mode.SKIP_TOOLS:
                turns += [call(str(t.name), **(t.args or {})) for t in tool_uses]
            if mode is Mode.EXTRA_TOOLS and not tool_uses:
                turns.append(call("get_order", order_ref="10432"))
            assert invocation.final_response is not None
            final = "".join(p.text or "" for p in invocation.final_response.parts or [])
            if mode is Mode.GUESSES:
                final = _without_questions(final)
            turns.append(say(final))
            scripts[user] = turns
    return scripts


def build(mode: Mode) -> LlmAgent:
    settings = Settings.from_env(os.environ)
    return build_agent(settings, model=ScriptedLlm(scripts=_scripts(mode)))
