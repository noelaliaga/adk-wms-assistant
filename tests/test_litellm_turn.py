"""A full turn through ADK's LiteLlm adapter, offline.

LiteLlm talks to providers through ``litellm.acompletion``. Here its client is
replaced by a stub that returns OpenAI-format responses, so the test covers the
adapter's own work: converting MCP tool declarations to OpenAI "tools",
parsing a tool call whose arguments are a JSON string, and sending the tool
result back. It does not prove that Anthropic or OpenAI accept these schemas;
only a live run can.
"""

from __future__ import annotations

import json
from typing import Any

from google.adk.models.lite_llm import LiteLlm, LiteLLMClient
from google.adk.runners import InMemoryRunner
from google.genai import types
from litellm import ModelResponse
from litellm.types.utils import ChatCompletionMessageToolCall, Choices, Function, Message, Usage

from conftest import SettingsFactory
from wms_assistant.factory import build_agent
from wms_assistant.toolsets import READ_TOOLS

QUESTION = "How many units of TDW-HLM-M are left, and where?"


class StubClient(LiteLLMClient):
    """Returns a tool call first, then a text answer. Records every request."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def acompletion(
        self, model: Any, messages: Any, tools: Any, **kwargs: Any
    ) -> ModelResponse:
        self.requests.append({"model": model, "messages": messages, "tools": tools, **kwargs})
        if len(self.requests) == 1:
            message = Message(
                content=None,
                role="assistant",
                tool_calls=[
                    ChatCompletionMessageToolCall(
                        id="call_1",
                        type="function",
                        function=Function(name="get_stock", arguments='{"sku": "TDW-HLM-M"}'),
                    )
                ],
            )
            finish = "tool_calls"
        else:
            message = Message(content="TDW-HLM-M: 9 at A-01-02, 24 at R-07-01.", role="assistant")
            finish = "stop"
        return ModelResponse(
            model=model,
            choices=[Choices(index=0, message=message, finish_reason=finish)],
            usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


async def test_a_tool_call_round_trip_through_litellm(make_settings: SettingsFactory) -> None:
    client = StubClient()
    llm = LiteLlm(model="openai/example-model", llm_client=client)
    agent = build_agent(make_settings(), model=llm)
    runner = InMemoryRunner(agent=agent, app_name="litellm_test")
    try:
        session = await runner.session_service.create_session(app_name="litellm_test", user_id="u")
        texts: list[str] = []
        results: list[types.FunctionResponse] = []
        async for event in runner.run_async(
            user_id="u",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=QUESTION)]),
        ):
            for part in event.content.parts or [] if event.content else []:
                if part.text:
                    texts.append(part.text)
                if part.function_response:
                    results.append(part.function_response)
    finally:
        await runner.close()

    assert "".join(texts) == "TDW-HLM-M: 9 at A-01-02, 24 at R-07-01."
    [result] = results
    assert result.name == "get_stock"
    assert "A-01-02" in json.dumps(result.response)

    first, second = client.requests
    assert first["model"] == "openai/example-model"
    # MCP schemas reach the provider request in OpenAI "tools" format.
    declared = {t["function"]["name"]: t["function"] for t in first["tools"]}
    assert sorted(declared) == sorted(READ_TOOLS)
    assert declared["get_stock"]["parameters"]["properties"]["sku"]["type"] == "string"
    assert first["messages"][0]["role"] in {"system", "developer"}
    # The tool result goes back as a "tool" message tied to the call id.
    tool_messages = [m for m in second["messages"] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["call_1"]
    assert "R-07-01" in tool_messages[0]["content"]
