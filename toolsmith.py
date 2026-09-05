"""Toolsmith: a terminal coding agent whose loop is written by hand.

No agent framework. The message list, the tool schemas, the tool-call
dispatch and every termination rule live in this file so you can read the
whole control flow in one sitting.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

load_dotenv()
console = Console()

DEFAULT_MODEL = "gpt-5-mini"

# A tool result the model cannot read is the same as no tool result. Big
# outputs get truncated in the middle, which keeps the head and the tail.
MAX_TOOL_RESULT_CHARS = 4000
COMMAND_TIMEOUT_SECONDS = 60

SYSTEM_PROMPT = """You are a coding agent working inside a single workspace directory.

Work in small steps. Look before you edit: read a file before rewriting it, and
list or grep before you guess at a path. Every path you pass to a tool is
relative to the workspace root.

When the task is done, call `finish` with a short summary of what changed. Do
not call `finish` until you have verified your work, usually by running the
tests. If you cannot make progress, call `finish` and say what blocked you."""


class ToolError(Exception):
    """A failure the model is expected to read, understand and recover from."""


class BudgetExceeded(Exception):
    """A limit this program enforces. The model has no say in it."""


# --------------------------------------------------------------------------
# Tool argument schemas
#
# Pydantic models are the single definition of each tool's arguments: they
# generate the JSON Schema the API sees and validate what comes back.
# --------------------------------------------------------------------------


class ReadFileArgs(BaseModel):
    """Read a UTF-8 text file from the workspace."""

    path: str = Field(description="File path relative to the workspace root.")
    start_line: int = Field(1, description="1-indexed line to start from.")
    max_lines: int = Field(400, description="Maximum number of lines to return.")


class WriteFileArgs(BaseModel):
    """Write a UTF-8 text file, creating parent directories as needed. Replaces the whole file."""

    path: str = Field(description="File path relative to the workspace root.")
    content: str = Field(description="The complete new contents of the file.")


class ListDirArgs(BaseModel):
    """List the entries of a directory in the workspace."""

    path: str = Field(".", description="Directory path relative to the workspace root.")


class GrepArgs(BaseModel):
    """Search the workspace for a regular expression and return matching lines with their paths."""

    pattern: str = Field(description="A Python regular expression.")
    path: str = Field(".", description="Directory or file to search, relative to the workspace root.")
    max_results: int = Field(60, description="Maximum number of matching lines to return.")


class RunCommandArgs(BaseModel):
    """Run a shell command in the workspace and return its exit code, stdout and stderr."""

    command: str = Field(description="The command to run, as you would type it in a shell.")
    reason: str = Field(description="One short sentence on why this command is needed.")


class FinishArgs(BaseModel):
    """Declare the task complete and stop. Call this exactly once, last."""

    summary: str = Field(description="What you changed and how you verified it.")


# --------------------------------------------------------------------------
# Tool implementations
#
# Every one of these returns a plain string. That string is the entire view
# the model gets of what happened, so it has to be short and specific.
# --------------------------------------------------------------------------


def _resolve(workspace: Path, path: str) -> Path:
    """Resolve a workspace-relative path, refusing anything that escapes it."""
    target = (workspace / path).resolve()
    if target != workspace and workspace not in target.parents:
        raise ToolError(f"path escapes the workspace: {path!r}")
    return target


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head, tail = text[: limit // 2], text[-limit // 2 :]
    dropped = len(text) - limit
    return f"{head}\n\n... [{dropped} characters omitted] ...\n\n{tail}"


def read_file(workspace: Path, args: ReadFileArgs) -> str:
    target = _resolve(workspace, args.path)
    if not target.is_file():
        raise ToolError(f"no such file: {args.path!r}. Use list_dir to see what exists.")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(args.start_line - 1, 0)
    window = lines[start : start + args.max_lines]
    numbered = "\n".join(f"{start + i + 1:>5}  {line}" for i, line in enumerate(window))
    footer = ""
    if start + len(window) < len(lines):
        footer = f"\n\n[showing lines {start + 1}-{start + len(window)} of {len(lines)}]"
    return _truncate(numbered + footer)


def write_file(workspace: Path, args: WriteFileArgs) -> str:
    target = _resolve(workspace, args.path)
    existed = target.is_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(args.content, encoding="utf-8")
    verb = "overwrote" if existed else "created"
    return f"{verb} {args.path} ({len(args.content.splitlines())} lines)"


def list_dir(workspace: Path, args: ListDirArgs) -> str:
    target = _resolve(workspace, args.path)
    if not target.is_dir():
        raise ToolError(f"not a directory: {args.path!r}")
    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
    if not entries:
        return f"{args.path} is empty"
    rows = [f"{'dir ' if e.is_dir() else 'file'}  {e.name}" for e in entries if e.name != ".git"]
    return _truncate("\n".join(rows))


def grep(workspace: Path, args: GrepArgs) -> str:
    import re

    try:
        pattern = re.compile(args.pattern)
    except re.error as exc:
        raise ToolError(f"invalid regular expression {args.pattern!r}: {exc}") from exc

    root = _resolve(workspace, args.path)
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    hits: list[str] = []
    for file in files:
        if ".git" in file.parts or "venv" in file.parts or "__pycache__" in file.parts:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{file.relative_to(workspace)}:{number}: {line.strip()}")
                if len(hits) >= args.max_results:
                    return _truncate("\n".join(hits) + f"\n\n[stopped at {args.max_results} matches]")
    return _truncate("\n".join(hits)) if hits else f"no matches for {args.pattern!r}"


def run_command(workspace: Path, args: RunCommandArgs) -> str:
    # Running under venv/bin/python does not put venv/bin on PATH, so `pytest`
    # is not found and the model reinvents a test harness instead of failing.
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"}
    try:
        proc = subprocess.run(
            args.command,
            shell=True,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(
            f"command timed out after {COMMAND_TIMEOUT_SECONDS}s: {args.command!r}. "
            "Try something narrower."
        ) from None

    parts = [f"exit code: {proc.returncode}"]
    if proc.stdout.strip():
        parts.append(f"stdout:\n{proc.stdout.rstrip()}")
    if proc.stderr.strip():
        parts.append(f"stderr:\n{proc.stderr.rstrip()}")
    return _truncate("\n\n".join(parts))


def finish(workspace: Path, args: FinishArgs) -> str:
    return args.summary


@dataclass(frozen=True)
class Tool:
    name: str
    args_model: type[BaseModel]
    run: Callable[[Path, Any], str]
    needs_approval: bool = False

    @property
    def description(self) -> str:
        return (self.args_model.__doc__ or "").strip()

    def schema(self) -> dict[str, Any]:
        params = self.args_model.model_json_schema()
        params.pop("title", None)
        params["additionalProperties"] = False
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": params},
        }


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool("read_file", ReadFileArgs, read_file),
        Tool("write_file", WriteFileArgs, write_file),
        Tool("list_dir", ListDirArgs, list_dir),
        Tool("grep", GrepArgs, grep),
        Tool("run_command", RunCommandArgs, run_command, needs_approval=True),
        Tool("finish", FinishArgs, finish),
    ]
}


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------


@dataclass
class Budget:
    """Termination guarantees. Checked in code, never asked for in the prompt."""

    max_iterations: int = 25
    max_seconds: float = 300.0
    max_tokens: int = 200_000
    iterations: int = 0
    tokens: int = 0
    started: float = field(default_factory=time.monotonic)

    def check(self) -> None:
        """Called before each model call, because checking after has already spent it."""
        if self.iterations >= self.max_iterations:
            raise BudgetExceeded(f"hit the iteration cap ({self.max_iterations})")
        elapsed = time.monotonic() - self.started
        if elapsed >= self.max_seconds:
            raise BudgetExceeded(f"hit the time cap ({self.max_seconds:.0f}s)")
        if self.tokens >= self.max_tokens:
            raise BudgetExceeded(f"hit the token cap ({self.max_tokens})")

    def summary(self) -> str:
        elapsed = time.monotonic() - self.started
        return f"{self.iterations} turns, {self.tokens} tokens, {elapsed:.1f}s"


# --------------------------------------------------------------------------
# Tool dispatch
# --------------------------------------------------------------------------


def dispatch(workspace: Path, name: str, raw_arguments: str, auto_approve: bool) -> str:
    """Validate and run one tool call, converting every failure into readable text."""
    tool = TOOLS.get(name)
    if tool is None:
        return f"ERROR: no tool named {name!r}. Available: {', '.join(TOOLS)}"

    try:
        args = tool.args_model.model_validate_json(raw_arguments)
    except ValidationError as exc:
        return f"ERROR: bad arguments for {name}: {exc.errors(include_url=False)}"

    if tool.needs_approval and not auto_approve:
        console.print(Panel(str(args), title=f"approve {name}?", border_style="yellow"))
        if console.input("  run it? [y/N] ").strip().lower() not in {"y", "yes"}:
            return "ERROR: the user declined to run that command. Try a different approach."

    try:
        return tool.run(workspace, args)
    except ToolError as exc:
        return f"ERROR: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


def agent_loop(
    task: str,
    workspace: Path,
    *,
    client: OpenAI,
    model: str,
    budget: Budget,
    auto_approve: bool = False,
    verbose: bool = False,
) -> str:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Workspace root: {workspace}\n\nTask: {task}"},
    ]
    schemas = [tool.schema() for tool in TOOLS.values()]

    while True:
        budget.check()
        budget.iterations += 1

        response = client.chat.completions.create(model=model, messages=messages, tools=schemas)
        budget.tokens += response.usage.total_tokens if response.usage else 0

        choice = response.choices[0]
        message = choice.message
        messages.append(message.model_dump(exclude_none=True))

        if verbose:
            console.print(
                Panel(
                    Syntax(json.dumps(messages[-1], indent=2), "json", word_wrap=True),
                    title=f"turn {budget.iterations} · finish_reason={choice.finish_reason}",
                    border_style="dim",
                )
            )

        if message.content:
            console.print(Panel(message.content.strip(), title="assistant", border_style="cyan"))

        # No tool calls means the model believes it is done talking. It did not
        # call finish, so treat it as an answer rather than a completed task.
        if not message.tool_calls:
            return message.content or "(the model stopped without saying anything)"

        for call in message.tool_calls:
            name = call.function.name
            console.print(f"[dim]→ {name}[/dim] {_preview(call.function.arguments)}")
            result = dispatch(workspace, name, call.function.arguments, auto_approve)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

            if verbose:
                console.print(Panel(result, title=f"{name} result", border_style="dim"))

            if name == "finish" and not result.startswith("ERROR:"):
                return result


def _preview(arguments: str, limit: int = 100) -> str:
    flat = " ".join(arguments.split())
    return flat if len(flat) <= limit else flat[:limit] + "..."


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="A coding agent with a hand-written loop.")
    parser.add_argument("task", help="What the agent should do.")
    parser.add_argument("-w", "--workspace", default="sandbox", help="Directory the agent may touch.")
    parser.add_argument("-m", "--model", default=os.environ.get("TOOLSMITH_MODEL", DEFAULT_MODEL))
    parser.add_argument("--max-iterations", type=int, default=25)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--max-tokens", type=int, default=200_000)
    parser.add_argument("-y", "--yes", action="store_true", help="Run commands without asking.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Dump the raw message list.")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        console.print(f"[red]no such workspace directory: {workspace}[/red]")
        return 2

    budget = Budget(
        max_iterations=args.max_iterations,
        max_seconds=args.max_seconds,
        max_tokens=args.max_tokens,
    )
    client = OpenAI(base_url=os.environ.get("TOOLSMITH_BASE_URL") or None)

    console.print(Panel(f"{args.task}\n\n[dim]{workspace}  ·  {args.model}[/dim]", title="toolsmith"))

    try:
        outcome = agent_loop(
            args.task,
            workspace,
            client=client,
            model=args.model,
            budget=budget,
            auto_approve=args.yes,
            verbose=args.verbose,
        )
        console.print(Panel(outcome, title="done", border_style="green"))
        status = 0
    except BudgetExceeded as exc:
        console.print(Panel(str(exc), title="stopped", border_style="red"))
        status = 1
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted[/yellow]")
        status = 130

    console.print(f"[dim]{budget.summary()}[/dim]")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
