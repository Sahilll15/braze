"""Termination guarantees, enforced in code rather than requested in the prompt."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from agent.errors import BudgetExceeded


@dataclass
class Budget:
    max_iterations: int = 25
    max_seconds: float = 300.0
    max_tokens: int = 200_000
    iterations: int = 0
    tokens: int = 0
    started: float = field(default_factory=time.monotonic)

    def check(self) -> None:
        """Called before each request, because checking after has already spent it."""
        if self.iterations >= self.max_iterations:
            raise BudgetExceeded(f"hit the iteration cap ({self.max_iterations})")
        if time.monotonic() - self.started >= self.max_seconds:
            raise BudgetExceeded(f"hit the time cap ({self.max_seconds:.0f}s)")
        if self.tokens >= self.max_tokens:
            raise BudgetExceeded(f"hit the token cap ({self.max_tokens})")

    def summary(self) -> str:
        return f"{self.iterations} turns, {self.tokens} tokens, {time.monotonic() - self.started:.1f}s"
