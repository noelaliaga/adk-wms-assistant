"""The ADK eval files are valid and ADK's own evaluator can run them offline.

The live run (`make eval`, a real model plus an LLM judge) is not part of the
test suite. Here a scripted agent replays each case's reference answer through
the real toolsets and server, and ADK's AgentEvaluator grades it with the
offline metrics (tool trajectory and ROUGE). This proves the files, the tool
names and arguments, and the metric configuration work. It says nothing about
how a real model scores.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator
from google.adk.evaluation.eval_config import EvalConfig
from google.adk.evaluation.eval_set import EvalSet

from conftest import REPO
from wms_assistant.toolsets import READ_TOOLS

EVALS = REPO / "evals"
EVALSET_FILE = EVALS / "wms_assistant.test.json"


def _eval_set() -> EvalSet:
    return EvalSet.model_validate_json(EVALSET_FILE.read_text(encoding="utf-8"))


def _config(name: str) -> EvalConfig:
    return EvalConfig.model_validate_json((EVALS / name).read_text(encoding="utf-8"))


def test_eval_set_is_well_formed() -> None:
    eval_set = _eval_set()
    ids = [c.eval_id for c in eval_set.eval_cases]
    assert len(ids) == len(set(ids)) >= 5
    for case in eval_set.eval_cases:
        assert case.conversation, case.eval_id
        assert case.rubrics, f"{case.eval_id} has no rubric"
        for invocation in case.conversation:
            assert invocation.final_response is not None
            data = invocation.intermediate_data
            assert data is not None
            assert hasattr(data, "tool_uses")
            # The set runs with writes off, so only read tools can appear.
            assert {t.name for t in data.tool_uses} <= set(READ_TOOLS), case.eval_id


def test_eval_set_covers_ask_before_assuming() -> None:
    ids = {c.eval_id for c in _eval_set().eval_cases}
    assert {
        "partial_sku_asks_first",
        "ambiguous_customer_asks_first",
        "write_request_with_writes_off",
        "injected_note_is_data",
    } <= ids


def test_live_config_uses_trajectory_response_and_rubric_metrics() -> None:
    live = _config("test_config.json")
    assert set(live.criteria) == {
        "tool_trajectory_avg_score",
        "response_match_score",
        "rubric_based_final_response_quality_v1",
    }
    # The offline config must not need a judge model (that would be a network call).
    offline = _config("offline_config.json")
    assert set(offline.criteria) == {"tool_trajectory_avg_score", "response_match_score"}


@pytest.fixture
def eval_env(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    monkeypatch.setenv("WMS_DB_PATH", str(db_path))
    monkeypatch.setenv("WMS_WRITE_POLICY", "off")
    # ADK's evaluator lists the tools once more after it has closed the runners
    # that shared this agent; that call waits for the MCP timeout before it
    # reconnects (observed with google-adk 2.9.1). A short timeout keeps the
    # test fast. It is a local wait, not a network call.
    monkeypatch.setenv("WMS_MCP_TIMEOUT_S", "5")
    for name in list(sys.modules):
        if name.startswith("offline_agents."):
            del sys.modules[name]


async def test_adk_evaluator_passes_a_replay_of_the_references(eval_env: None) -> None:
    await AgentEvaluator.evaluate_eval_set(
        agent_module="offline_agents.replay",
        eval_set=_eval_set(),
        eval_config=_config("offline_config.json"),
        num_runs=1,
        print_detailed_results=False,
    )


async def test_adk_evaluator_fails_an_agent_that_skips_the_tools(eval_env: None) -> None:
    """Negative control: same final text, no tool calls. The trajectory metric must fail."""
    with pytest.raises(AssertionError, match="tool_trajectory_avg_score"):
        await AgentEvaluator.evaluate_eval_set(
            agent_module="offline_agents.skip_tools",
            eval_set=_eval_set(),
            eval_config=_config("offline_config.json"),
            num_runs=1,
            print_detailed_results=False,
        )
