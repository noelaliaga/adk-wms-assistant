"""Scripted stand-ins for the assistant, loadable by ADK's AgentEvaluator.

``replay`` answers every eval case with its own reference trajectory and
response. ``skip_tools`` answers with the reference text but calls no tools,
a negative control that the trajectory metric must fail.
"""
