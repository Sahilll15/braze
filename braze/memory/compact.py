"""Keeping the context window under control.

Compaction summarises the oldest half of the transcript into one note and drops
the raw turns from the live context. The database keeps them either way, so what
is lost is only what the model sees, never the record.
"""

from __future__ import annotations

import json
import os

import tiktoken

# The window the model is given, not the run's total spend cap. Overridable so a
# demo can set it low enough to watch compaction fire in a short run.
CONTEXT_WINDOW = int(os.environ.get("BRAZE_CONTEXT_WINDOW", 128_000))
COMPACT_AT = 0.6

# Compaction aims well below the trigger rather than just under it. Landing at
# 0.59 means compacting again next turn, and paying for a summary every turn.
TARGET = 0.35

# Below this there is nothing worth summarising, and cutting into the last few
# turns removes the context the model is actively using.
MIN_KEEP_GROUPS = 4

# A summary of a handful of short turns costs more tokens than it saves.
MIN_DROP_TOKENS = 1_500

# Per-message framing the API adds around role and content.
MESSAGE_OVERHEAD = 4

SUMMARY_PROMPT = """You are compacting the earlier part of a coding agent's own transcript so that
it can keep working with less context. Write a dense note addressed to the agent
as "you".

Keep: what the task is, which files were read and what they contain, which files
were changed and how, which commands were run and what they returned, what failed
and why, and anything already ruled out.

Drop: pleasantries, restatements, and reasoning that led nowhere.

Do not invent progress. If something was attempted but never verified, say that
it was never verified. Plain prose, under 400 words, no headings."""

_encoding = None


def _encoder():
    global _encoding
    if _encoding is None:
        # Registries lag new model names, and the wrong encoder is still a far
        # better estimate than no count at all.
        try:
            _encoding = tiktoken.encoding_for_model(os.environ.get("BRAZE_MODEL", ""))
        except (KeyError, ValueError):
            _encoding = tiktoken.get_encoding("o200k_base")
    return _encoding


def count_message(message: dict) -> int:
    enc = _encoder()
    total = MESSAGE_OVERHEAD + len(enc.encode(message.get("role") or ""))
    total += len(enc.encode(message.get("content") or ""))
    for call in message.get("tool_calls") or []:
        function = call.get("function", {})
        total += len(enc.encode(function.get("name") or ""))
        total += len(enc.encode(function.get("arguments") or ""))
    return total


def count(messages: list[dict]) -> int:
    return sum(count_message(m) for m in messages)


def should_compact(messages: list[dict]) -> bool:
    return count(messages) > CONTEXT_WINDOW * COMPACT_AT


def groups(messages: list[dict]) -> list[tuple[int, int]]:
    """Index ranges that have to move together.

    An assistant message with tool_calls and its tool results are one unit: the
    API rejects a tool message whose matching assistant call is no longer there.
    """
    spans, index = [], 0
    while index < len(messages):
        start = index
        index += 1
        if messages[start].get("tool_calls"):
            while index < len(messages) and messages[index].get("role") == "tool":
                index += 1
        spans.append((start, index))
    return spans


def plan(messages: list[dict]) -> list[int]:
    """Which message indices to drop. Empty when there is nothing worth cutting."""
    spans = groups(messages)

    pinned = 0
    while pinned < len(spans) and messages[spans[pinned][0]].get("role") == "system":
        pinned += 1

    candidates = spans[pinned:]
    if len(candidates) <= MIN_KEEP_GROUPS:
        return []
    droppable = candidates[: len(candidates) - MIN_KEEP_GROUPS]

    need = count(messages) - int(CONTEXT_WINDOW * TARGET)
    running, cut = 0, 0
    for position, (start, end) in enumerate(droppable):
        running += sum(count_message(messages[i]) for i in range(start, end))
        cut = position + 1
        if running >= need:
            break

    if running < MIN_DROP_TOKENS:
        return []
    return [i for start, end in droppable[:cut] for i in range(start, end)]


def _as_transcript(messages: list[dict]) -> str:
    lines = []
    for message in messages:
        role = message.get("role", "?")
        if role == "tool":
            lines.append(f"[tool result] {(message.get('content') or '')[:1200]}")
            continue
        if message.get("content"):
            lines.append(f"[{role}] {message['content']}")
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            lines.append(f"[{role} calls {function.get('name')}] {function.get('arguments')}")
    return "\n".join(lines)


def summarise(client, model: str, messages: list[dict]) -> str:
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": _as_transcript(messages)},
        ],
    )
    return completion.choices[0].message.content or ""


def note(summary: str) -> dict:
    return {
        "role": "system",
        "content": (
            "Earlier turns of this task have been summarised to save context. "
            "Treat the following as your own record of what already happened.\n\n"
            + summary
        ),
    }


def sawtooth(history: list[tuple[int, int, int]], width: int = 40) -> str:
    """The token count over time, as bars. A picture of the budget, in a terminal."""
    if not history:
        return "  no budget history for this run\n"

    peak = max(max(before, after) for _, before, after in history) or 1
    lines = []
    for turn, before, after in history:
        bar = "#" * max(1, round(before / peak * width))
        drop = " -> {:,}".format(after) if after < before else ""
        lines.append(f"  {turn:>3}  {bar:<{width}}  {before:>7,}{drop}")
    lines.append(f"\n  peak {peak:,} tokens, window {CONTEXT_WINDOW:,}, "
                 f"compacting above {int(CONTEXT_WINDOW * COMPACT_AT):,}")
    return "\n".join(lines) + "\n"
