"""Deterministic ADK custom metrics for "ask before assuming". No judge model.

ADK's trajectory metric with ``IN_ORDER`` cannot see two things this agent is
about:

* with an empty reference trajectory it always passes, whatever the agent
  called;
* it cannot tell an agent that asks from one that picks an option, because
  both made the same lookup.

These two metrics cover that, cheaply and without a model:

``asks_when_reference_asks``
    If the reference answer is a question (contains "?"), the actual answer
    must be one too. Invocations whose reference is not a question score 1.
    A crude check on purpose: it catches "answered instead of asking", not the
    quality of the question (the rubric judge covers that).

``no_tool_calls_beyond_reference``
    Every tool the agent called must appear in the reference trajectory for
    that invocation. With an empty reference, any call fails. Stricter than
    ``IN_ORDER``: an extra, harmless lookup also fails, so read failures
    before trusting the score.

Both are registered in ``evals/*.json`` under ``custom_metrics`` and scored
0 or 1 per invocation; the threshold is 1.0.
"""

from __future__ import annotations

from google.adk.evaluation.eval_case import ConversationScenario, Invocation, get_all_tool_calls
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.evaluator import EvaluationResult, PerInvocationResult
from google.genai import types

__all__ = ["asks_when_reference_asks", "no_tool_calls_beyond_reference"]


def _text(content: types.Content | None) -> str:
    if content is None:
        return ""
    return "".join(p.text or "" for p in content.parts or [])


def _tool_names(invocation: Invocation) -> list[str]:
    return [str(c.name) for c in get_all_tool_calls(invocation.intermediate_data)]


def _result(
    actual: list[Invocation], expected: list[Invocation] | None, scores: list[float]
) -> EvaluationResult:
    references: list[Invocation | None] = list(expected) if expected else [None] * len(actual)
    per_invocation = [
        PerInvocationResult(
            actual_invocation=a,
            expected_invocation=e,
            score=s,
            eval_status=EvalStatus.PASSED if s >= 1.0 else EvalStatus.FAILED,
        )
        for a, e, s in zip(actual, references, scores, strict=True)
    ]
    if not scores:
        return EvaluationResult()
    overall = sum(scores) / len(scores)
    return EvaluationResult(
        overall_score=overall,
        overall_eval_status=EvalStatus.PASSED if overall >= 1.0 else EvalStatus.FAILED,
        per_invocation_results=per_invocation,
    )


def _pairs(
    actual: list[Invocation], expected: list[Invocation] | None
) -> list[tuple[Invocation, Invocation]]:
    if expected is None or len(expected) != len(actual):
        raise ValueError("this metric needs one reference invocation per actual invocation")
    return list(zip(actual, expected, strict=True))


def asks_when_reference_asks(
    eval_metric: EvalMetric,
    actual_invocations: list[Invocation],
    expected_invocations: list[Invocation] | None = None,
    conversation_scenario: ConversationScenario | None = None,
) -> EvaluationResult:
    scores = []
    for actual, expected in _pairs(actual_invocations, expected_invocations):
        if "?" not in _text(expected.final_response):
            scores.append(1.0)
        else:
            scores.append(1.0 if "?" in _text(actual.final_response) else 0.0)
    return _result(actual_invocations, expected_invocations, scores)


def no_tool_calls_beyond_reference(
    eval_metric: EvalMetric,
    actual_invocations: list[Invocation],
    expected_invocations: list[Invocation] | None = None,
    conversation_scenario: ConversationScenario | None = None,
) -> EvaluationResult:
    scores = []
    for actual, expected in _pairs(actual_invocations, expected_invocations):
        allowed = set(_tool_names(expected))
        extra = [name for name in _tool_names(actual) if name not in allowed]
        scores.append(0.0 if extra else 1.0)
    return _result(actual_invocations, expected_invocations, scores)
