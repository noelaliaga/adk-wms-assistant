"""Builds the ADK agent from settings. No network access happens here."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.genai import types

from wms_assistant.approval import BeforeToolCallback, make_approval_callback
from wms_assistant.config import ModelBackend, Settings, WritePolicy
from wms_assistant.prompts import build_instruction
from wms_assistant.telemetry import Telemetry
from wms_assistant.toolsets import build_toolsets

AGENT_NAME = "wms_assistant"


def resolve_model(settings: Settings) -> str | BaseLlm:
    """Gemini goes through ADK's native client; anything else through LiteLLM."""
    if settings.backend is ModelBackend.GEMINI:
        return settings.model
    # Imported lazily: LiteLLM is an optional extra.
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(model=settings.model)


def build_agent(
    settings: Settings,
    *,
    model: str | BaseLlm | None = None,
    telemetry: Telemetry | None = None,
) -> LlmAgent:
    """Return the assistant. ``model`` overrides the configured one (tests use a fake)."""
    telemetry = telemetry or Telemetry()
    before_tool: list[BeforeToolCallback] = [telemetry.before_tool]
    if settings.write_policy is not WritePolicy.OFF:
        before_tool.append(make_approval_callback(settings.write_policy))
    return LlmAgent(
        name=AGENT_NAME,
        description="Answers warehouse questions from WMS tools and asks before assuming.",
        model=model if model is not None else resolve_model(settings),
        instruction=build_instruction(settings.write_policy),
        tools=list(build_toolsets(settings)),
        # Operational answers should not vary between runs of the same question.
        generate_content_config=types.GenerateContentConfig(temperature=0.0),
        before_tool_callback=list(before_tool),
        after_tool_callback=telemetry.after_tool,
        after_model_callback=telemetry.after_model,
    )
