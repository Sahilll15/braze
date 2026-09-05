"""Turning one tool call into one tool result.

Nothing here may raise. Every outcome, including a refusal and an unexpected
crash, becomes a string the model can read and act on.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from agent import ui
from agent.errors import ToolError
from agent.permissions import Policy
from agent.tools import TOOLS, resolve


def dispatch(workspace: Path, name: str, raw_arguments: str, policy: Policy) -> str:
    tool = TOOLS.get(name)
    if tool is None:
        return f"ERROR: no tool named {name!r}. Available: {', '.join(TOOLS)}"

    try:
        args = tool.args_model.model_validate_json(raw_arguments)
    except ValidationError as exc:
        return f"ERROR: bad arguments for {name}: {exc.errors(include_url=False)}"

    try:
        if tool.is_command and policy.command_needs_approval(args.command):
            answer = ui.confirm_command(args.command, args.reason)
            if answer == "always":
                policy.remember(args.command, persist_to=workspace)
            elif answer != "yes":
                return "ERROR: the user declined to run that command. Try a different approach."

        if tool.mutates and policy.write_needs_approval():
            refusal = _confirm_mutation(workspace, name, args, policy)
            if refusal:
                return refusal

        return tool.run(workspace, args)
    except ToolError as exc:
        return f"ERROR: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {type(exc).__name__}: {exc}"


def _confirm_mutation(workspace: Path, name: str, args, policy: Policy) -> str | None:
    """Show what the write would do and ask. Returns a refusal string, or None to proceed."""
    target = resolve(workspace, args.path)
    before = target.read_text(encoding="utf-8") if target.is_file() else ""

    if name == "edit_file":
        if before.count(args.old_text) != 1:
            return None  # let the tool raise the precise error rather than diffing a bad match
        after = before.replace(args.old_text, args.new_text)
    else:
        after = args.content

    if before == after:
        return None

    answer = ui.confirm_write(args.path, before, after)
    if answer == "always":
        policy.auto_approve = True
        return None
    if answer != "yes":
        return "ERROR: the user declined that change. Ask what they want instead."
    return None
