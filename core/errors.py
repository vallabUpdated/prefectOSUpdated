# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Pipeline exceptions."""


class BudgetExhaustedError(RuntimeError):
    """Raised when the MAX_AGENTS cap is hit."""

class ApprovalRejectedError(RuntimeError):
    """Raised when the user rejects an agent's output."""


