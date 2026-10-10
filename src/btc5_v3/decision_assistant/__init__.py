"""Fail-closed UP/DOWN/WAIT decision contract."""

from .evaluation import Decision, DecisionInput, DecisionPolicy, evaluate

__all__ = ["Decision", "DecisionInput", "DecisionPolicy", "evaluate"]
