"""What the agent may do without asking.

Two gates, deliberately separate. A write is reviewed by looking at its diff; a
command is reviewed by reading the command. They fail differently, so they are
approved differently.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = ".toolsmith.json"

# Reading and listing cannot damage anything, so they are allowed by default.
# Anything that writes, deletes, installs or reaches the network is not.
DEFAULT_ALLOWED_COMMANDS: tuple[str, ...] = (
    "ls", "cat", "head", "tail", "wc", "file", "stat",
    "pwd", "which", "echo", "date",
    "git status", "git diff", "git log", "git show", "git branch",
    "pytest", "python -m pytest", "python3 -m pytest",
)


@dataclass
class Policy:
    """Decides, per action, whether to run it, ask, or refuse."""

    allowed_commands: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_COMMANDS))
    auto_approve: bool = False
    session_allowed: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, workspace: Path, auto_approve: bool = False) -> "Policy":
        policy = cls(auto_approve=auto_approve)
        config = workspace / CONFIG_NAME
        if config.is_file():
            try:
                data = json.loads(config.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return policy
            policy.allowed_commands += list(data.get("allowed_commands", []))
        return policy

    def save(self, workspace: Path) -> None:
        (workspace / CONFIG_NAME).write_text(
            json.dumps({"allowed_commands": sorted(set(self.allowed_commands))}, indent=2) + "\n",
            encoding="utf-8",
        )

    def command_needs_approval(self, command: str) -> bool:
        if self.auto_approve:
            return False
        return not self._matches(command, self.allowed_commands + sorted(self.session_allowed))

    def write_needs_approval(self) -> bool:
        return not self.auto_approve

    def remember(self, command: str, *, persist_to: Path | None = None) -> None:
        prefix = self.prefix_of(command)
        self.session_allowed.add(prefix)
        if persist_to is not None:
            self.allowed_commands.append(prefix)
            self.save(persist_to)

    @staticmethod
    def prefix_of(command: str) -> str:
        """The part of a command worth remembering: the program and its subcommand.

        Remembering the whole string would never match twice; remembering only
        the program would approve `git push` because you once allowed `git log`.
        """
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()
        if not parts:
            return command.strip()
        if len(parts) > 1 and not parts[1].startswith("-"):
            return f"{parts[0]} {parts[1]}"
        return parts[0]

    @staticmethod
    def _matches(command: str, allowed: list[str]) -> bool:
        # A shell operator can smuggle a second command past a prefix match, so
        # anything containing one is always reviewed in full.
        if any(token in command for token in ("&&", "||", ";", "|", "`", "$(", ">", "<")):
            return False
        stripped = command.strip()
        return any(stripped == rule or stripped.startswith(rule + " ") for rule in allowed)
