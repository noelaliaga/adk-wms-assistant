"""A scripted stand-in for a real model. No network, no API keys.

``ScriptedLlm`` is a real ``BaseLlm`` subclass, so ADK drives it exactly like
Gemini or LiteLlm: it builds the request (instruction, tool declarations,
history), calls ``generate_content_async`` and executes whatever function calls
come back through the real MCP toolsets.

The script is keyed by the user's message. For each model turn after that
message the next scripted ``Content`` is returned. The fake ignores tool
results, so it tests the wiring and the safety configuration, not a model.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping, Sequence
from typing import Any

from google.adk.models import BaseLlm, LlmCapabilities
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field


def call(name: str, **args: Any) -> types.Content:
    return types.Content(
        role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]
    )


def say(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text)])


def _text(content: types.Content) -> str:
    return "".join(p.text for p in content.parts or [] if p.text)


class ScriptExhaustedError(RuntimeError):
    pass


class ScriptedLlm(BaseLlm):
    model: str = "scripted"
    scripts: Mapping[str, Sequence[types.Content]]
    requests: list[LlmRequest] = Field(default_factory=list)

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=False)

    def _position(self, request: LlmRequest) -> tuple[str, int]:
        """(last user text, number of model turns since that message)."""
        contents = request.contents
        for i in range(len(contents) - 1, -1, -1):
            content = contents[i]
            if content.role == "user" and _text(content):
                later = contents[i + 1 :]
                return _text(content), sum(1 for c in later if c.role == "model")
        raise ScriptExhaustedError("the request has no user message")

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        user_text, step = self._position(llm_request)
        script = self.scripts.get(user_text)
        if script is None:
            raise ScriptExhaustedError(f"no script for user message {user_text!r}")
        if step >= len(script):
            raise ScriptExhaustedError(f"script for {user_text!r} has no turn {step}")
        yield LlmResponse(content=script[step])
