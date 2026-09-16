"""Full ADK turns with a scripted model and the real mcp-logistica server.

The model is fake (tests/fakes.py); everything else is real: ADK's runner and
flow, the MCP toolsets, the stdio server and the SQLite triggers.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from conftest import SettingsFactory
from fakes import ScriptedLlm, call, say
from wms_assistant.factory import build_agent
from wms_assistant.toolsets import READ_TOOLS, WRITE_TOOLS

APP = "wms_assistant_test"
USER = "tester"
CONFIRMATION_TOOL = "adk_request_confirmation"


@dataclass
class Turn:
    text: str = ""
    calls: list[types.FunctionCall] = field(default_factory=list)
    responses: list[types.FunctionResponse] = field(default_factory=list)


class Session:
    def __init__(self, runner: InMemoryRunner, session_id: str) -> None:
        self.runner = runner
        self.session_id = session_id

    async def send(self, message: types.Content) -> Turn:
        turn = Turn()
        async for event in self.runner.run_async(
            user_id=USER, session_id=self.session_id, new_message=message
        ):
            for part in event.content.parts or [] if event.content else []:
                if part.text:
                    turn.text += part.text
                if part.function_call:
                    turn.calls.append(part.function_call)
                if part.function_response:
                    turn.responses.append(part.function_response)
        return turn

    async def say(self, text: str) -> Turn:
        return await self.send(types.Content(role="user", parts=[types.Part(text=text)]))

    async def answer_confirmation(self, call_id: str, *, confirmed: bool) -> Turn:
        response = types.FunctionResponse(
            id=call_id, name=CONFIRMATION_TOOL, response={"confirmed": confirmed}
        )
        return await self.send(
            types.Content(role="user", parts=[types.Part(function_response=response)])
        )


@dataclass
class Harness:
    llm: ScriptedLlm
    session: Session


async def _open(
    settings_env: dict[str, str],
    make_settings: SettingsFactory,
    scripts: dict[str, Sequence[types.Content]],
) -> AsyncIterator[Harness]:
    llm = ScriptedLlm(scripts=scripts)
    runner = InMemoryRunner(
        agent=build_agent(make_settings(**settings_env), model=llm), app_name=APP
    )
    try:
        created = await runner.session_service.create_session(app_name=APP, user_id=USER)
        yield Harness(llm, Session(runner, created.id))
    finally:
        await runner.close()


def _payload(response: types.FunctionResponse) -> dict[str, Any]:
    """The JSON the MCP server returned, as ADK hands it to the model."""
    raw = response.response or {}
    structured = raw.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    text = raw["content"][0]["text"]
    parsed = json.loads(text)
    assert isinstance(parsed, dict)
    return parsed


def _order(db: Path, order_id: int) -> tuple[str, int]:
    with closing(sqlite3.connect(db)) as conn:
        status = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()[0]
        audits = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    return str(status), int(audits)


STOCK_QUESTION = "How many units of TDW-HLM-M are left, and where?"
STOCK_SCRIPT = [
    call("get_stock", sku="TDW-HLM-M"),
    say("TDW-HLM-M: 9 units at A-01-02 and 24 at R-07-01."),
]


async def test_one_turn_with_a_read_tool_call(make_settings: SettingsFactory) -> None:
    async for h in _open({}, make_settings, {STOCK_QUESTION: STOCK_SCRIPT}):
        turn = await h.session.say(STOCK_QUESTION)

        assert [c.name for c in turn.calls] == ["get_stock"]
        [response] = turn.responses
        stock = _payload(response)
        assert stock["sku"] == "TDW-HLM-M"
        assert {loc["location"]: loc["on_hand"] for loc in stock["locations"]} == {
            "A-01-02": 9,
            "R-07-01": 24,
        }
        assert turn.text == "TDW-HLM-M: 9 units at A-01-02 and 24 at R-07-01."

        # What ADK actually sent to the model.
        first, second = h.llm.requests
        assert first.config.system_instruction is not None
        assert "Ask before assuming" in str(first.config.system_instruction)
        assert sorted(first.tools_dict) == sorted(READ_TOOLS)
        assert first.config.temperature == 0.0
        assert any(
            p.function_response and p.function_response.name == "get_stock"
            for c in second.contents
            for p in c.parts or []
        )


async def test_ambiguous_name_comes_back_as_a_question_not_an_answer(
    make_settings: SettingsFactory,
) -> None:
    question = "What's the status of Martínez's order?"
    script = [call("get_order", order_ref="Martínez"), say("Which order id do you mean?")]
    async for h in _open({}, make_settings, {question: script}):
        turn = await h.session.say(question)
        payload = _payload(turn.responses[0])
        assert payload["outcome"] == "needs_clarification"
        assert [c["order_id"] for c in payload["candidates"]] == [10432, 10412, 10409, 10401]


WRITE_REQUEST = "Mark order 10432 as a stock issue, the gloves are short."
WRITE_SCRIPT = [
    call(
        "set_order_status",
        order_ref="10432",
        status="stock_issue",
        reason="Only 1 unit of TDW-GLV-L at A-02-01; order needs 3",
    ),
    say("Done."),
]


def _pending_confirmation(turn: Turn) -> str:
    [request] = [c for c in turn.calls if c.name == CONFIRMATION_TOOL]
    assert request.args is not None
    assert request.args["originalFunctionCall"]["name"] == "set_order_status"
    assert request.id is not None
    return request.id


@pytest.mark.parametrize("policy", ["dry_run", "on"])
async def test_a_write_waits_for_user_approval(
    make_settings: SettingsFactory, db_path: Path, policy: str
) -> None:
    before = _order(db_path, 10432)
    async for h in _open(
        {"WMS_WRITE_POLICY": policy}, make_settings, {WRITE_REQUEST: WRITE_SCRIPT}
    ):
        turn = await h.session.say(WRITE_REQUEST)
        _pending_confirmation(turn)
        [pending] = turn.responses
        assert "requires confirmation" in str(pending.response)
        # The model was asked once; ADK paused instead of letting it continue.
        assert len(h.llm.requests) == 1
        assert sorted(h.llm.requests[0].tools_dict) == sorted(READ_TOOLS + WRITE_TOOLS)
    assert _order(db_path, 10432) == before


async def test_a_rejected_write_changes_nothing(
    make_settings: SettingsFactory, db_path: Path
) -> None:
    before = _order(db_path, 10432)
    async for h in _open({"WMS_WRITE_POLICY": "on"}, make_settings, {WRITE_REQUEST: WRITE_SCRIPT}):
        call_id = _pending_confirmation(await h.session.say(WRITE_REQUEST))
        turn = await h.session.answer_confirmation(call_id, confirmed=False)
        [rejected] = turn.responses
        assert rejected.response == {"error": "This tool call is rejected."}
    assert _order(db_path, 10432) == before


async def test_an_approved_write_is_applied_and_audited_as_agent(
    make_settings: SettingsFactory, db_path: Path
) -> None:
    status_before, audits_before = _order(db_path, 10432)
    assert status_before == "picking"
    async for h in _open({"WMS_WRITE_POLICY": "on"}, make_settings, {WRITE_REQUEST: WRITE_SCRIPT}):
        call_id = _pending_confirmation(await h.session.say(WRITE_REQUEST))
        turn = await h.session.answer_confirmation(call_id, confirmed=True)
        [applied] = turn.responses
        assert _payload(applied)["outcome"] == "applied"
        assert turn.text == "Done."
    assert _order(db_path, 10432) == ("stock_issue", audits_before + 1)
    with closing(sqlite3.connect(db_path)) as conn:
        actor = conn.execute("SELECT actor FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert actor == "agent"


async def test_an_approved_dry_run_writes_nothing(
    make_settings: SettingsFactory, db_path: Path
) -> None:
    before = _order(db_path, 10432)
    async for h in _open(
        {"WMS_WRITE_POLICY": "dry_run"}, make_settings, {WRITE_REQUEST: WRITE_SCRIPT}
    ):
        call_id = _pending_confirmation(await h.session.say(WRITE_REQUEST))
        turn = await h.session.answer_confirmation(call_id, confirmed=True)
        assert _payload(turn.responses[0])["outcome"] == "dry_run"
    assert _order(db_path, 10432) == before


async def test_the_server_still_refuses_a_forbidden_status_after_approval(
    make_settings: SettingsFactory, db_path: Path
) -> None:
    """Approval is not a bypass: the user can approve, the server still says no."""
    request = "10437 is on the dock, mark it shipped."
    script = [
        call("set_order_status", order_ref="10437", status="shipped", reason="On the dock"),
        say("I can't mark it shipped."),
    ]
    before = _order(db_path, 10437)
    async for h in _open({"WMS_WRITE_POLICY": "on"}, make_settings, {request: script}):
        call_id = _pending_confirmation(await h.session.say(request))
        turn = await h.session.answer_confirmation(call_id, confirmed=True)
        [refused] = turn.responses
        assert refused.response is not None
        assert refused.response.get("isError") is True
        assert "an agent cannot set status 'shipped'" in json.dumps(refused.response)
    assert _order(db_path, 10437) == before
