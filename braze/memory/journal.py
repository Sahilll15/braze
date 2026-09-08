"""The write-ahead protocol, and what to do with a half-finished step.

A crash between "the model asked for this" and "this happened" is the whole
problem. Committing the intent before acting turns an unknown into a known
question: the step row exists and says `started`, so something was in flight.
Answering that question is what the resume policy below is for.
"""

from __future__ import annotations

import hashlib
import json

from ..tools import confine
from . import compact
from .store import DONE, FINISHED, RUNNING, STOPPED, Store

# What a resume is allowed to do with a step that was in flight when we died.
#
#   replay  re-running it changes nothing that was not already changed
#   verify  we can tell from the file itself whether it landed
#   report  we cannot know, so say so rather than guess
RESUME_POLICY = {
    "read_file": "replay",
    "list_dir": "replay",
    "grep": "replay",
    "write_file": "replay",
    "finish": "replay",
    "edit_file": "verify",
    "run_command": "report",
}

# Only the tools whose resume decision depends on it. Recording a hash nobody
# reads is state that goes stale without anyone noticing.
FINGERPRINTED = {"edit_file": "path"}

ABSENT = "absent"

INTERRUPTED_UNKNOWN = (
    "Error: this call was interrupted by a crash and may or may not have run. "
    "Check the current state before assuming either way, then continue."
)
INTERRUPTED_APPLIED = (
    "This call was interrupted by a crash, but the file has changed since, so it "
    "appears to have been applied. Read the file to confirm before editing it again."
)


def to_dict(message) -> dict:
    """Normalise an SDK message object to the minimal shape the API accepts back.

    model_dump() also returns refusal and audio keys that some providers reject,
    and the live list has to match what went into the database exactly.
    """
    if isinstance(message, dict):
        return message
    body: dict = {"role": message.role, "content": message.content}
    if getattr(message, "tool_calls", None):
        body["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in message.tool_calls
        ]
    return body


def fingerprint(tool: str, raw_arguments: str) -> str | None:
    """Hash the file a call is about to change, so a resume can tell if it did."""
    key = FINGERPRINTED.get(tool)
    if key is None:
        return None
    try:
        path = json.loads(raw_arguments).get(key)
    except (json.JSONDecodeError, AttributeError):
        return None
    if not path:
        return None
    try:
        target = confine.resolve(path)
    except (PermissionError, OSError):
        return None
    if not target.is_file():
        return ABSENT
    return hashlib.sha256(target.read_bytes()).hexdigest()


def unresolved(messages: list[dict]) -> list[dict]:
    """Tool calls the model asked for that never got a result written back."""
    answered = {
        m.get("tool_call_id") for m in messages if m.get("role") == "tool"
    }
    return [
        call
        for message in messages
        for call in (message.get("tool_calls") or [])
        if call.get("id") not in answered
    ]


class Journal:
    """Durable state for one run. Every method here commits before it returns."""

    def __init__(self, store: Store, run_id: str, turn: int = 0, tokens: int = 0):
        self.store = store
        self.run_id = run_id
        self.turn = turn
        self.tokens = tokens

    # -- lifecycle ----------------------------------------------------------

    @classmethod
    def start(cls, store: Store, task: str, workspace: str, model: str) -> "Journal":
        return cls(store, store.create_run(task, workspace, model))

    @classmethod
    def reopen(cls, store: Store, run_id: str) -> "Journal":
        run = store.get_run(run_id)
        journal = cls(store, run_id, run.turns, run.tokens)
        store.update_run(run_id, status=RUNNING)
        return journal

    def close(self, status: str, stopped_reason: str = "", answer: str = "") -> None:
        self.store.update_run(
            self.run_id, status=status, stopped_reason=stopped_reason or None,
            answer=answer or None, turns=self.turn, tokens=self.tokens,
        )

    # -- messages -----------------------------------------------------------

    def remember(self, message) -> dict:
        """Store a message and hand back the exact dict to put in the live list."""
        body = to_dict(message)
        self.store.append_message(
            self.run_id, self.turn, body, compact.count_message(body)
        )
        return body

    def mark(self, turn: int, tokens: int) -> None:
        self.turn, self.tokens = turn, tokens
        self.store.update_run(self.run_id, turns=turn, tokens=tokens)

    # -- steps --------------------------------------------------------------

    def begin(self, call_id: str, tool: str, raw_arguments: str) -> None:
        self.store.begin_step(
            self.run_id, call_id, self.turn, tool, raw_arguments,
            fingerprint(tool, raw_arguments),
        )

    def done(self, call_id: str, output: str) -> None:
        self.store.finish_step(self.run_id, call_id, output)

    # -- compaction ---------------------------------------------------------

    def maybe_compact(self, client, model: str, messages: list[dict]) -> bool:
        """Summarise the oldest turns into a note. Returns whether anything moved."""
        before = compact.count(messages)
        if before <= compact.CONTEXT_WINDOW * compact.COMPACT_AT:
            self.store.record_budget(self.run_id, self.turn, before, before)
            return False

        doomed = compact.plan(messages)
        if not doomed:
            self.store.record_budget(self.run_id, self.turn, before, before)
            return False

        summary = compact.summarise(client, model, [messages[i] for i in doomed])
        note = compact.note(summary)

        # A summary longer than the turns it replaces is a net loss, and one
        # rejected here is cheaper than one that ships.
        freed = sum(compact.count_message(messages[i]) for i in doomed)
        if not summary.strip() or freed - compact.count_message(note) <= 0:
            self.store.record_budget(self.run_id, self.turn, before, before)
            return False

        seqs = self.store.live_seqs(self.run_id)
        self.store.drop_messages(
            self.run_id, [seqs[i] for i in doomed if i < len(seqs)], self.turn
        )
        stored = self.remember(note)

        kept = [m for i, m in enumerate(messages) if i not in set(doomed)]
        # The note sits directly after the pinned system prompts, where the turns
        # it replaces used to be.
        insert_at = 0
        while insert_at < len(kept) and kept[insert_at].get("role") == "system":
            insert_at += 1
        messages[:] = kept[:insert_at] + [stored] + kept[insert_at:]

        self.store.record_budget(self.run_id, self.turn, before, compact.count(messages))
        return True

    # -- resume -------------------------------------------------------------

    def settle(self, messages: list[dict], run_tool) -> list[str]:
        """Finish any tool call that was in flight when the last run died.

        Appends the missing tool results to `messages` in place and returns a
        line per call describing what was decided, for the user to read.
        """
        notes = []
        for call in unresolved(messages):
            call_id = call["id"]
            tool = call["function"]["name"]
            raw_arguments = call["function"]["arguments"]
            step = self.store.get_step(self.run_id, call_id)

            if step is not None and step.status == DONE:
                output, why = step.output or "", "already done, result restored"
            elif step is None:
                self.begin(call_id, tool, raw_arguments)
                output, why = run_tool(tool, raw_arguments), "never started, ran now"
                self.done(call_id, output)
            else:
                output, why = self._settle_started(step, tool, raw_arguments, run_tool)
                self.done(call_id, output)

            messages.append(self.remember(
                {"role": "tool", "tool_call_id": call_id, "content": output}
            ))
            notes.append(f"{tool}: {why}")
        return notes

    def _settle_started(self, step, tool, raw_arguments, run_tool) -> tuple[str, str]:
        policy = RESUME_POLICY.get(tool, "report")

        if policy == "replay":
            return run_tool(tool, raw_arguments), "safe to repeat, ran again"

        if policy == "verify":
            now = fingerprint(tool, raw_arguments)
            if now is not None and now == step.fingerprint:
                return (
                    run_tool(tool, raw_arguments),
                    "file unchanged, so the edit never landed, ran again",
                )
            return INTERRUPTED_APPLIED, "file changed, so the edit landed, not repeated"

        return INTERRUPTED_UNKNOWN, "cannot be repeated safely, reported to the model"


def open_run(store: Store, prefix: str):
    """Look a run up by id prefix and say why it cannot be resumed, if it cannot."""
    run = store.find_run(prefix)
    if run is None:
        return None, f"no run matches {prefix!r}"
    if run.status == FINISHED:
        return None, f"run {run.id} already finished"
    if run.status == STOPPED:
        return None, f"run {run.id} hit a limit and stopped: {run.stopped_reason}"
    return run, ""
