"""Entry point. One task and exit, or an interactive session."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from agent import ui
from agent.budget import Budget
from agent.errors import BudgetExceeded
from agent.loop import SYSTEM_PROMPT, run_task
from agent.permissions import Policy

DEFAULT_MODEL = "gpt-5-mini"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="toolsmith", description="A terminal coding agent.")
    parser.add_argument("task", nargs="?", help="What to do. Omit for an interactive session.")
    parser.add_argument("-w", "--workspace", default=".", help="The only directory the agent may touch.")
    parser.add_argument("-m", "--model", default=os.environ.get("TOOLSMITH_MODEL", DEFAULT_MODEL))
    parser.add_argument("--max-iterations", type=int, default=25)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--max-tokens", type=int, default=200_000)
    parser.add_argument("-y", "--yes", action="store_true", help="Never ask for approval.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Dump the raw message list.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        ui.outcome(f"no such workspace directory: {workspace}", style="red", title="error")
        return 2

    client = OpenAI(base_url=os.environ.get("TOOLSMITH_BASE_URL") or None)
    policy = Policy.load(workspace, auto_approve=args.yes)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Workspace root: {workspace}"},
    ]

    ui.banner(args.task or "interactive session", workspace, args.model)

    tasks = iter([args.task]) if args.task else _prompt_forever()
    status = 0

    for task in tasks:
        if task is None:
            break
        messages.append({"role": "user", "content": task})
        # A fresh budget per task: the caps are about one unit of work, not about
        # how long you have had the session open.
        budget = Budget(args.max_iterations, args.max_seconds, args.max_tokens)
        try:
            result = run_task(
                messages,
                workspace,
                client=client,
                model=args.model,
                budget=budget,
                policy=policy,
                verbose=args.verbose,
            )
            ui.outcome(result)
        except BudgetExceeded as exc:
            ui.outcome(str(exc), style="red", title="stopped")
            status = 1
        except KeyboardInterrupt:
            ui.note("\ninterrupted")
            status = 130
            break
        ui.note(budget.summary())

    return status


def _prompt_forever():
    """Yield tasks typed at the prompt until the user leaves."""
    while True:
        try:
            line = ui.console.input("\n[bold]>[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            ui.note("\nbye")
            return
        if not line:
            continue
        if line in {"exit", "quit", ":q"}:
            ui.note("bye")
            return
        yield line
