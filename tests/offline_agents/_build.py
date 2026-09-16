from __future__ import annotations

import os
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.evaluation.eval_set import EvalSet
from google.genai import types

from fakes import ScriptedLlm, call, say
from wms_assistant.config import Settings
from wms_assistant.factory import build_agent

EVALSET = Path(__file__).resolve().parents[2] / "evals" / "wms_assistant.test.json"


def _scripts(*, with_tools: bool) -> dict[str, list[types.Content]]:
    eval_set = EvalSet.model_validate_json(EVALSET.read_text(encoding="utf-8"))
    scripts: dict[str, list[types.Content]] = {}
    for case in eval_set.eval_cases:
        for invocation in case.conversation or []:
            user = "".join(p.text or "" for p in invocation.user_content.parts or [])
            turns: list[types.Content] = []
            data = invocation.intermediate_data
            if with_tools and data is not None and hasattr(data, "tool_uses"):
                turns += [call(str(t.name), **(t.args or {})) for t in data.tool_uses]
            assert invocation.final_response is not None
            final = "".join(p.text or "" for p in invocation.final_response.parts or [])
            turns.append(say(final))
            scripts[user] = turns
    return scripts


def build(*, with_tools: bool) -> LlmAgent:
    settings = Settings.from_env(os.environ)
    return build_agent(settings, model=ScriptedLlm(scripts=_scripts(with_tools=with_tools)))
