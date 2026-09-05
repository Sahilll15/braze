"""Tool implementations and the registry.

Every tool returns a plain string. That string is the model's entire view of
what happened, so it is truncated, numbered and phrased for a reader who has to
decide what to do next.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from agent.errors import ToolError
from agent.schemas import (
    EditFileArgs,
    FinishArgs,
    GrepArgs,
    ListDirArgs,
    ReadFileArgs,
    RunCommandArgs,
    WriteFileArgs,
)

MAX_TOOL_RESULT_CHARS = 4000
COMMAND_TIMEOUT_SECONDS = 60
SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", ".pytest_cache"}


def resolve(workspace: Path, path: str) -> Path:
    """Resolve a workspace-relative path, refusing anything that escapes it.

    The check has to happen after resolving: pathlib lets an absolute right-hand
    side win, so `workspace / "/etc/passwd"` is simply `/etc/passwd`.
    """
    target = (workspace / path).resolve()
    if target != workspace and workspace not in target.parents:
        raise ToolError(f"path escapes the workspace: {path!r}")
    return target


def truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head, tail = text[: limit // 2], text[-limit // 2 :]
    return f"{head}\n\n... [{len(text) - limit} characters omitted] ...\n\n{tail}"


def read_file(workspace: Path, args: ReadFileArgs) -> str:
    target = resolve(workspace, args.path)
    if not target.is_file():
        raise ToolError(f"no such file: {args.path!r}. Use list_dir to see what exists.")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(args.start_line - 1, 0)
    window = lines[start : start + args.max_lines]
    body = "\n".join(f"{start + i + 1:>5}  {line}" for i, line in enumerate(window))
    if start + len(window) < len(lines):
        body += f"\n\n[showing lines {start + 1}-{start + len(window)} of {len(lines)}]"
    return truncate(body)


def write_file(workspace: Path, args: WriteFileArgs) -> str:
    target = resolve(workspace, args.path)
    existed = target.is_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(args.content, encoding="utf-8")
    return f"{'overwrote' if existed else 'created'} {args.path} ({len(args.content.splitlines())} lines)"


def edit_file(workspace: Path, args: EditFileArgs) -> str:
    target = resolve(workspace, args.path)
    if not target.is_file():
        raise ToolError(f"no such file: {args.path!r}. Use list_dir to see what exists.")

    original = target.read_text(encoding="utf-8")
    occurrences = original.count(args.old_text)
    if occurrences == 0:
        raise ToolError(
            f"old_text was not found in {args.path!r}. Read the file again and copy the "
            "exact text, including indentation."
        )
    # Ambiguity is the failure that silently edits the wrong call site, so a
    # non-unique match is refused rather than resolved by guessing.
    if occurrences > 1:
        raise ToolError(
            f"old_text appears {occurrences} times in {args.path!r}. Include more "
            "surrounding lines so it matches exactly once."
        )

    target.write_text(original.replace(args.old_text, args.new_text), encoding="utf-8")
    removed = len(args.old_text.splitlines())
    added = len(args.new_text.splitlines())
    return f"edited {args.path} (-{removed} +{added} lines)"


def list_dir(workspace: Path, args: ListDirArgs) -> str:
    target = resolve(workspace, args.path)
    if not target.is_dir():
        raise ToolError(f"not a directory: {args.path!r}")
    entries = [e for e in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
               if e.name not in SKIP_DIRS]
    if not entries:
        return f"{args.path} is empty"
    return truncate("\n".join(f"{'dir ' if e.is_dir() else 'file'}  {e.name}" for e in entries))


def grep(workspace: Path, args: GrepArgs) -> str:
    try:
        pattern = re.compile(args.pattern)
    except re.error as exc:
        raise ToolError(f"invalid regular expression {args.pattern!r}: {exc}") from exc

    root = resolve(workspace, args.path)
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    hits: list[str] = []
    for file in files:
        if SKIP_DIRS & set(file.parts):
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{file.relative_to(workspace)}:{number}: {line.strip()}")
                if len(hits) >= args.max_results:
                    return truncate("\n".join(hits) + f"\n\n[stopped at {args.max_results} matches]")
    return truncate("\n".join(hits)) if hits else f"no matches for {args.pattern!r}"


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
            f"command timed out after {COMMAND_TIMEOUT_SECONDS}s: {args.command!r}. Try something narrower."
        ) from None

    parts = [f"exit code: {proc.returncode}"]
    if proc.stdout.strip():
        parts.append(f"stdout:\n{proc.stdout.rstrip()}")
    if proc.stderr.strip():
        parts.append(f"stderr:\n{proc.stderr.rstrip()}")
    return truncate("\n\n".join(parts))


def finish(workspace: Path, args: FinishArgs) -> str:
    return args.summary


@dataclass(frozen=True)
class Tool:
    name: str
    args_model: type[BaseModel]
    run: Callable[[Path, Any], str]
    mutates: bool = False
    is_command: bool = False

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
        Tool("write_file", WriteFileArgs, write_file, mutates=True),
        Tool("edit_file", EditFileArgs, edit_file, mutates=True),
        Tool("list_dir", ListDirArgs, list_dir),
        Tool("grep", GrepArgs, grep),
        Tool("run_command", RunCommandArgs, run_command, is_command=True),
        Tool("finish", FinishArgs, finish),
    ]
}
