"""Failures, split by who is expected to act on them."""

from __future__ import annotations


class ToolError(Exception):
    """A failure the model is expected to read, understand and recover from.

    The message is handed straight back to the model, so it must say what went
    wrong and what to try instead.
    """


class BudgetExceeded(Exception):
    """A limit this program enforces. The model has no say in it."""


class Declined(Exception):
    """The user refused an action. Not an error, a decision."""
