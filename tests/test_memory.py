"""What a crash is allowed to do, and what it is not."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from braze.memory import compact, journal as J
from braze.memory.store import DONE, Store
from braze.tools import confine


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "runs.db")
    yield s
    s.close()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "work"
    root.mkdir()
    monkeypatch.setattr(confine, "WORKSPACE", root)
    return root


def call(call_id, tool, **arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": tool, "arguments": json.dumps(arguments)},
    }


def assistant(*calls):
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


def result(call_id, content="ok"):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


# -- serialisation ---------------------------------------------------------


def test_to_dict_keeps_only_what_the_api_accepts_back():
    sdk = SimpleNamespace(
        role="assistant", content=None, refusal=None, audio=None,
        tool_calls=[SimpleNamespace(
            id="c1", function=SimpleNamespace(name="grep", arguments='{"pattern":"x"}')
        )],
    )
    body = J.to_dict(sdk)
    assert set(body) == {"role", "content", "tool_calls"}
    assert body["tool_calls"][0] == {
        "id": "c1", "type": "function",
        "function": {"name": "grep", "arguments": '{"pattern":"x"}'},
    }


def test_to_dict_passes_plain_dicts_through():
    body = {"role": "user", "content": "hi"}
    assert J.to_dict(body) is body


# -- finding the half-finished turn ----------------------------------------


def test_unresolved_finds_calls_with_no_result():
    messages = [
        {"role": "user", "content": "go"},
        assistant(call("a", "read_file", file_path="x"), call("b", "grep", pattern="y")),
        result("a"),
    ]
    assert [c["id"] for c in J.unresolved(messages)] == ["b"]


def test_unresolved_is_empty_when_every_call_was_answered():
    messages = [assistant(call("a", "grep", pattern="y")), result("a")]
    assert J.unresolved(messages) == []


# -- the store -------------------------------------------------------------


def test_dropped_messages_leave_the_context_but_stay_on_disk(store):
    run_id = store.create_run("t", "/tmp", "m")
    for i in range(4):
        store.append_message(run_id, 0, {"role": "user", "content": str(i)}, 1)
    store.drop_messages(run_id, [1, 2], turn=3)

    assert [m["content"] for m in store.live_messages(run_id)] == ["0", "3"]
    assert len(store.all_messages(run_id)) == 4


def test_find_run_accepts_a_prefix(store):
    run_id = store.create_run("t", "/tmp", "m")
    assert store.find_run(run_id[:6]).id == run_id
    assert store.find_run("zzzz") is None


# -- resume: the whole point ----------------------------------------------


def crashed_run(store, workspace, tool, arguments):
    """A run whose last tool call was committed as started and never finished."""
    run_id = store.create_run("t", str(workspace), "m")
    store.append_message(run_id, 1, {"role": "user", "content": "t"}, 1)
    store.append_message(run_id, 1, assistant(call("c1", tool, **arguments)), 1)
    raw = json.dumps(arguments)
    store.begin_step(run_id, "c1", 1, tool, raw, J.fingerprint(tool, raw))
    return run_id


def test_a_finished_step_is_restored_and_never_re_run(store, workspace):
    run_id = crashed_run(store, workspace, "grep", {"pattern": "x", "path": "."})
    store.finish_step(run_id, "c1", "3 hits")

    ran = []
    journal = J.Journal(store, run_id, turn=1)
    messages = store.live_messages(run_id)
    notes = journal.settle(messages, lambda *a: ran.append(a) or "should not happen")

    assert ran == []
    assert messages[-1]["content"] == "3 hits"
    assert "already done" in notes[0]


def test_a_step_that_never_started_is_simply_run(store, workspace):
    run_id = store.create_run("t", str(workspace), "m")
    store.append_message(run_id, 1, assistant(call("c1", "grep", pattern="x")), 1)

    journal = J.Journal(store, run_id, turn=1)
    messages = store.live_messages(run_id)
    notes = journal.settle(messages, lambda tool, raw: "fresh result")

    assert messages[-1]["content"] == "fresh result"
    assert "never started" in notes[0]
    assert store.get_step(run_id, "c1").status == DONE


def test_an_interrupted_edit_re_runs_when_the_file_did_not_change(store, workspace):
    (workspace / "a.py").write_text("old\n")
    run_id = crashed_run(
        store, workspace, "edit_file",
        {"path": "a.py", "old_text": "old", "new_text": "new"},
    )

    ran = []
    journal = J.Journal(store, run_id, turn=1)
    messages = store.live_messages(run_id)
    notes = journal.settle(messages, lambda tool, raw: ran.append(tool) or "edited a.py")

    assert ran == ["edit_file"]
    assert "never landed" in notes[0]


def test_an_interrupted_edit_is_not_repeated_when_the_file_changed(store, workspace):
    target = workspace / "a.py"
    target.write_text("old\n")
    run_id = crashed_run(
        store, workspace, "edit_file",
        {"path": "a.py", "old_text": "old", "new_text": "new"},
    )
    # The write landed, and only then did the process die.
    target.write_text("new\n")

    ran = []
    journal = J.Journal(store, run_id, turn=1)
    messages = store.live_messages(run_id)
    notes = journal.settle(messages, lambda tool, raw: ran.append(tool) or "edited again")

    assert ran == []
    assert messages[-1]["content"] == J.INTERRUPTED_APPLIED
    assert "landed" in notes[0]


def test_an_interrupted_command_is_never_repeated(store, workspace):
    run_id = crashed_run(
        store, workspace, "run_command",
        {"command": "curl -X POST https://example.com/deploy"},
    )

    ran = []
    journal = J.Journal(store, run_id, turn=1)
    messages = store.live_messages(run_id)
    notes = journal.settle(messages, lambda tool, raw: ran.append(tool) or "ran twice")

    assert ran == []
    assert messages[-1]["content"] == J.INTERRUPTED_UNKNOWN
    assert "cannot be repeated" in notes[0]


def test_every_tool_has_a_resume_policy():
    from braze.cli import TOOL_FUNCTIONS

    assert set(TOOL_FUNCTIONS) <= set(J.RESUME_POLICY)


def test_fingerprint_of_a_missing_file_is_absent(workspace):
    assert J.fingerprint("edit_file", json.dumps({"path": "nope.py"})) == J.ABSENT


def test_fingerprint_tracks_content(workspace):
    (workspace / "a.py").write_text("hello")
    raw = json.dumps({"path": "a.py"})
    assert J.fingerprint("edit_file", raw) == hashlib.sha256(b"hello").hexdigest()


def test_fingerprint_is_none_for_tools_whose_resume_does_not_need_it():
    assert J.fingerprint("run_command", json.dumps({"command": "ls"})) is None
    assert J.fingerprint("write_file", json.dumps({"path": "a.py"})) is None


def test_every_fingerprinted_tool_is_one_that_reads_it_back():
    assert all(J.RESUME_POLICY[t] == "verify" for t in J.FINGERPRINTED)


# -- compaction ------------------------------------------------------------


def test_groups_never_split_an_assistant_from_its_tool_results():
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        assistant(call("a", "grep", pattern="x"), call("b", "grep", pattern="y")),
        result("a"), result("b"),
        {"role": "assistant", "content": "done"},
    ]
    assert compact.groups(messages) == [(0, 1), (1, 2), (2, 5), (5, 6)]


def test_plan_leaves_short_transcripts_alone():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert compact.plan(messages) == []


@pytest.fixture
def small_window(monkeypatch):
    monkeypatch.setattr(compact, "CONTEXT_WINDOW", 4_000)
    return 4_000


def test_plan_pins_system_messages_and_keeps_the_recent_turns(small_window):
    messages = [{"role": "system", "content": "s"}]
    for i in range(12):
        messages.append({"role": "user", "content": f"question {i} " * 50})
        messages.append({"role": "assistant", "content": f"answer {i} " * 50})

    doomed = compact.plan(messages)

    assert doomed, "a long transcript should have something to drop"
    assert 0 not in doomed, "the system prompt is never dropped"
    assert max(doomed) < len(messages) - compact.MIN_KEEP_GROUPS
    assert doomed == list(range(min(doomed), max(doomed) + 1)), "drops are contiguous"


def test_plan_refuses_when_the_saving_would_not_pay_for_the_summary(small_window):
    """A summary of four short turns costs more tokens than it frees."""
    messages = [{"role": "system", "content": "s"}]
    for i in range(8):
        messages.append({"role": "user", "content": f"q{i}"})
        messages.append({"role": "assistant", "content": f"a{i}"})

    assert compact.plan(messages) == []


def test_plan_aims_below_the_trigger_not_just_under_it(small_window):
    """Landing at 59 percent means compacting again next turn, and paying again."""
    messages = [{"role": "system", "content": "s"}]
    for i in range(20):
        messages.append({"role": "user", "content": f"question {i} " * 60})
        messages.append({"role": "assistant", "content": f"answer {i} " * 60})

    doomed = set(compact.plan(messages))
    kept = compact.count([m for i, m in enumerate(messages) if i not in doomed])

    assert kept < small_window * compact.COMPACT_AT


def test_a_dropped_range_never_orphans_a_tool_result():
    messages = [{"role": "system", "content": "s"}]
    for i in range(10):
        messages.append({"role": "user", "content": f"q{i} " * 40})
        messages.append(assistant(call(f"c{i}", "grep", pattern="x" * 200)))
        messages.append(result(f"c{i}", "hit " * 40))

    kept = [m for i, m in enumerate(messages) if i not in set(compact.plan(messages))]

    offered = {c["id"] for m in kept for c in (m.get("tool_calls") or [])}
    answered = {m["tool_call_id"] for m in kept if m.get("role") == "tool"}
    assert answered <= offered


def test_count_message_survives_a_null_content():
    assert compact.count_message(assistant(call("a", "grep", pattern="x"))) > 0


def test_sawtooth_reports_the_drop():
    assert "-> 300" in compact.sawtooth([(1, 100, 100), (2, 900, 300)])
