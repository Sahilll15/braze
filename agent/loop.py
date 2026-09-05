"""The loop.

Everything else in this package is a feature around these forty lines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openai import OpenAI

from agent import ui
from agent.budget import Budget
from agent.dispatch import dispatch
from agent.permissions import Policy
from agent.tools import TOOLS

SYSTEM_PROMPT = """You are a coding agent working inside a single workspace directory.

Work in small steps. Look before you edit: read a file before changing it, and
list or grep before guessing at a path. Every path you pass to a tool is
relative to the workspace root.

Prefer edit_file over write_file for changes to a file that already exists.
write_file replaces the whole file, so use it only for new files or genuine
rewrites.

When the task is done, call `finish` with a short summary. Do not call `finish`
until you have verified your work, usually by running the tests. If you cannot
make progress, call `finish` and say what blocked you."""


def stream_turn(client: OpenAI, model: str, messages: list[dict[str, Any]], schemas: list[dict]):
    """One request, rendered as it arrives.

    Returns (assistant_message_dict, usage). The SDK gives deltas, so tool call
    arguments arrive in fragments and have to be concatenated by index.
    """
    text_parts: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    printed_header = False

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=schemas,
        stream=True,
        stream_options={"include_usage": True},
    )

    usage = None
    for chunk in stream:
        if chunk.usage is not None:
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        if delta.content:
            if not printed_header:
                printed_header = True
            text_parts.append(delta.content)
            ui.console.print(delta.content, end="", markup=False, highlight=False)

        for fragment in delta.tool_calls or []:
            call = calls.setdefault(
                fragment.index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
            )
            if fragment.id:
                call["id"] = fragment.id
            if fragment.function and fragment.function.name:
                call["function"]["name"] = fragment.function.name
            if fragment.function and fragment.function.arguments:
                call["function"]["arguments"] += fragment.function.arguments

    if printed_header:
        ui.console.print()

    message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return message, usage


def run_task(
    messages: list[dict[str, Any]],
    workspace: Path,
    *,
    client: OpenAI,
    model: str,
    budget: Budget,
    policy: Policy,
    verbose: bool = False,
) -> str:
    """Drive one task to completion, appending to `messages` in place."""
    schemas = [tool.schema() for tool in TOOLS.values()]

    while True:
        budget.check()
        budget.iterations += 1

        message, usage = stream_turn(client, model, messages, schemas)
        budget.tokens += usage.total_tokens if usage else 0
        messages.append(message)

        if verbose:
            ui.raw_messages(messages, f"turn {budget.iterations}")

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return message.get("content") or "(the model stopped without saying anything)"

        for call in tool_calls:
            name = call["function"]["name"]
            arguments = call["function"]["arguments"]
            ui.tool_call_line(name, arguments)

            result = dispatch(workspace, name, arguments, policy)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})

            if verbose or result.startswith("ERROR:"):
                ui.tool_result(name, result)

            if name == "finish" and not result.startswith("ERROR:"):
                return result
