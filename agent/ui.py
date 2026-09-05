"""Everything the human sees.

Kept apart from the loop so that what the agent does and how it is displayed can
change independently.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

console = Console()


def preview_args(arguments: str, limit: int = 96) -> str:
    flat = " ".join(arguments.split())
    return flat if len(flat) <= limit else flat[:limit] + "..."


def tool_call_line(name: str, arguments: str) -> None:
    console.print(f"[dim]→[/dim] [bold]{name}[/bold] [dim]{preview_args(arguments)}[/dim]")


def assistant_text(text: str) -> None:
    if text.strip():
        console.print(Panel(text.strip(), border_style="cyan", padding=(0, 1)))


def tool_result(name: str, result: str) -> None:
    style = "red" if result.startswith("ERROR:") else "dim"
    console.print(Panel(result, title=f"{name} result", border_style=style, padding=(0, 1)))


def raw_messages(messages: list[dict[str, Any]], title: str) -> None:
    console.print(
        Panel(
            Syntax(json.dumps(messages[-1], indent=2), "json", word_wrap=True),
            title=title,
            border_style="dim",
        )
    )


def render_diff(path: str, before: str, after: str) -> Text:
    lines = difflib.unified_diff(
        before.splitlines(), after.splitlines(), fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""
    )
    out = Text()
    for line in lines:
        if line.startswith("+") and not line.startswith("+++"):
            out.append(line + "\n", style="green")
        elif line.startswith("-") and not line.startswith("---"):
            out.append(line + "\n", style="red")
        elif line.startswith("@@"):
            out.append(line + "\n", style="cyan")
        else:
            out.append(line + "\n", style="dim")
    return out or Text("(no textual change)\n", style="dim")


def confirm_write(path: str, before: str, after: str) -> str:
    """Show the diff and ask. Returns 'yes', 'no', or 'always'."""
    console.print(Panel(render_diff(path, before, after), title=f"edit {path}", border_style="yellow"))
    answer = console.input("  apply? [y]es / [n]o / [a]lways: ").strip().lower()
    return {"y": "yes", "yes": "yes", "a": "always", "always": "always"}.get(answer, "no")


def confirm_command(command: str, reason: str) -> str:
    """Ask before running a command. Returns 'yes', 'no', or 'always'."""
    body = Text()
    body.append(command + "\n", style="bold")
    body.append(reason, style="dim")
    console.print(Panel(body, title="run this?", border_style="yellow"))
    answer = console.input("  [y]es / [n]o / [a]lways allow this command: ").strip().lower()
    return {"y": "yes", "yes": "yes", "a": "always", "always": "always"}.get(answer, "no")


def banner(task: str, workspace: Path, model: str) -> None:
    console.print(Panel(f"{task}\n\n[dim]{workspace}  ·  {model}[/dim]", title="toolsmith"))


def outcome(text: str, style: str = "green", title: str = "done") -> None:
    console.print(Panel(text, title=title, border_style=style))


def note(text: str) -> None:
    console.print(f"[dim]{text}[/dim]")
