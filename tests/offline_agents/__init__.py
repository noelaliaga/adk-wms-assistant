"""Scripted stand-ins for the assistant, loadable by ADK's AgentEvaluator.

``replay`` answers every eval case with its own reference trajectory and
response. The others are negative controls that a metric must fail:

* ``skip_tools``: reference text, no tool calls (trajectory metric);
* ``guesses``: reference tools, but every clarifying question is replaced by
  a statement (``asks_when_reference_asks``);
* ``extra_tools``: reference behaviour, plus a lookup where the reference
  makes none (``no_tool_calls_beyond_reference``; ``IN_ORDER`` passes it).
"""
