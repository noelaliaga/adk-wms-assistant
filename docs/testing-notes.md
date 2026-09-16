# Testing notes

## Environment the suite was run in

2026-09-16, macOS, on Python 3.11.15, 3.12.14, 3.13.15 and 3.14.6, with the
versions in [`constraints.txt`](../constraints.txt): `google-adk` 2.9.1,
`google-genai` 2.23.0, `mcp` 1.30.0, `litellm` 1.85.7 (1.96.2 on 3.14, which
has no 1.85.7 build), ruff 0.16.8, mypy 2.3.1, pytest 9.1.1.

`make install` and CI install with `-c constraints.txt`, so these versions are
what a fresh install gets. Transitive dependencies are not pinned.

`mcp-logistica` was at commit `6e9763d7ab50e01567ada3b27f772b32cef1328f`;
CI checks out that commit.

## What "offline" means here

- The test process cannot open TCP/UDP connections or resolve names
  (`tests/conftest.py`). The MCP servers are child processes on pipes; the
  guard does not reach into them.
- The model is `ScriptedLlm` (`tests/fakes.py`). Its "token" counts are made
  up, only so telemetry can be tested.
- LiteLLM is exercised through ADK's `LiteLlm` with a stub client
  (`tests/test_litellm_turn.py`): the adapter code runs, no provider is called.

## ADK 2.9.1 quirks worth knowing

- **Tool re-listing after the evaluator closes its runners.** ADK's evaluator
  lists the tools once more after closing the runners that shared the agent;
  that call waits for the MCP timeout before reconnecting. The evaluator tests
  and `make eval-offline` use `WMS_MCP_TIMEOUT_S=5`, and `make eval-offline`
  prints a `ConnectionError: MCP session connection lost` traceback after the
  results. It is expected and does not change the result.
- **Generic confirmation text.** `McpTool` asks for approval with
  "Please approve or reject the tool call set_order_status() ..." and
  `adk run` prints only that hint. `agents/wms_assistant/approval.py` requests
  the confirmation first, with the arguments in the hint.
- **`adk eval` has no `--num_runs`.** Repeat the command, or call
  `AgentEvaluator.evaluate(..., num_runs=N)` from Python.
