import argparse
import json
from dataclasses import dataclass, field
import readline  # noqa: F401  gives input() arrow-key history
import time

from dotenv import load_dotenv
from openai import OpenAI

from . import memory, ui
from .config import get_api_key
from .memory import compact
from .tools import confine
from .tools.edit_file import edit_file
from .tools.finish import finish
from .tools.grep import grep
from .tools.list_dir import list_dir
from .tools.read_file import read_file
from .tools.run_command import run_command
from .tools.text import truncate
from .tools.write_file import write_file

MODEL = "gpt-5.5"

# Termination is enforced here, not asked for in the prompt.
MAX_TURNS = 25
MAX_SECONDS = 300
MAX_TOKENS = 200_000

TOOL_FUNCTIONS = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_dir": list_dir,
    "grep": grep,
    "run_command": run_command,
    "finish": finish,
}

SYSTEM_PROMPT = (
    "You are a coding agent working inside one workspace directory. "
    "Work in small steps and look before you edit: read a file before changing it, "
    "and list or grep before guessing at a path. Every path you pass to a tool is "
    "relative to the workspace root. Prefer edit_file over write_file for files that "
    "already exist. Call finish when the task is done and you have verified it, "
    "usually by running the tests. Only answer questions about code."
)

STR = {"type": "string"}


def schema(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


TOOL_SCHEMAS = [
    schema("read_file", "Read a text file and return its contents with line numbers.",
           {"file_path": {**STR, "description": "Path to the file."}},
           ["file_path"]),
    schema("write_file", "Create a new file or replace one entirely.",
           {"path": {**STR, "description": "Path to the file."},
            "content": {**STR, "description": "The complete new contents."}},
           ["path", "content"]),
    schema("edit_file",
           "Replace one exact block of text in a file. Prefer this over write_file for existing files.",
           {"path": {**STR, "description": "Path to the file."},
            "old_text": {**STR, "description": "Exact text to replace, copied from the file including indentation. Include enough surrounding lines to make it unique."},
            "new_text": {**STR, "description": "Text to put in its place. Empty string deletes."}},
           ["path", "old_text", "new_text"]),
    schema("list_dir", "List the files and directories at a path.",
           {"path": {**STR, "description": "Directory to list."}},
           ["path"]),
    schema("grep", "Search files for a regular expression.",
           {"pattern": {**STR, "description": "A Python regular expression."},
            "path": {**STR, "description": "File or directory to search."}},
           ["pattern", "path"]),
    schema("run_command", "Run a shell command and return its output.",
           {"command": {**STR, "description": "The command to run."}},
           ["command"]),
    schema("finish", "Declare the task complete and stop.",
           {"summary": {**STR, "description": "What you did and how you checked it."}},
           ["summary"]),
]


ARG_SHOWN = {
    "read_file": "file_path", "write_file": "path", "edit_file": "path",
    "list_dir": "path", "grep": "pattern", "run_command": "command", "finish": None,
}


def describe(name: str, raw_arguments: str) -> str:
    """The one argument worth showing. A JSON blob is not scannable."""
    key = ARG_SHOWN.get(name)
    if key is None:
        return ""
    try:
        value = str(json.loads(raw_arguments).get(key, ""))
    except json.JSONDecodeError:
        return raw_arguments[:40]
    return value if len(value) <= 44 else value[:41] + "..."


def summarise(name: str, result: str) -> str:
    """A short right-hand note saying what came back."""
    if result.startswith("Error:"):
        return "failed"
    if name == "read_file":
        return f"{len(result.splitlines())} lines"
    if name in {"write_file", "edit_file"}:
        return result.split("(")[-1].rstrip(")") if "(" in result else "ok"
    if name == "list_dir":
        return f"{len(result.splitlines())} entries"
    if name == "grep":
        return "no matches" if result.startswith("no matches") else f"{len(result.splitlines())} hits"
    if name == "run_command":
        first = result.splitlines()[0] if result else ""
        return first.replace("exit code: ", "exit ")
    return ""


def run_tool(name: str, raw_arguments: str) -> str:
    """Run one tool call. Never raises, because a raise here kills the whole run."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return f"Error: no tool named {name!r}. Available: {', '.join(TOOL_FUNCTIONS)}"
    try:
        args = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        return f"Error: arguments for {name} were not valid JSON: {exc}"
    try:
        return truncate(str(fn(**args)))
    except TypeError as exc:
        return f"Error: wrong arguments for {name}: {exc}"
    except PermissionError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}"


@dataclass
class RunResult:
    """What a run did, as data. The UI renders this; an eval scores it."""

    turns: int = 0
    tokens: int = 0
    seconds: float = 0.0
    tool_calls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    answer: str = ""
    stopped_reason: str = ""

    @property
    def finished(self) -> bool:
        """Whether the agent declared itself done, which is not the same as correct."""
        return "finish" in self.tool_calls


def run_task(client, messages, verbose: bool, quiet: bool = False,
             journal=None) -> RunResult:
    """Drive one task to completion, appending to `messages` in place.

    With a journal, every state transition is committed to SQLite before the
    side effect it describes, which is what makes `--resume` possible. Without
    one the loop behaves exactly as it did before, which is what the eval wants.
    """
    result = RunResult()
    turns = journal.turn if journal else 0
    tokens = journal.tokens if journal else 0
    started = time.monotonic()

    while True:
        if turns >= MAX_TURNS:
            result.stopped_reason = f"turn cap ({MAX_TURNS})"
            if not quiet:
                ui.stopped(result.stopped_reason)
            break
        if time.monotonic() - started >= MAX_SECONDS:
            result.stopped_reason = f"time cap ({MAX_SECONDS}s)"
            if not quiet:
                ui.stopped(result.stopped_reason)
            break
        if tokens >= MAX_TOKENS:
            result.stopped_reason = f"token cap ({MAX_TOKENS})"
            if not quiet:
                ui.stopped(result.stopped_reason)
            break

        turns += 1
        if journal:
            journal.mark(turns, tokens)

        with ui.Spinner(enabled=not quiet):
            completion = client.chat.completions.create(
                model=MODEL, tools=TOOL_SCHEMAS, messages=messages,
            )
        tokens += completion.usage.total_tokens

        message = completion.choices[0].message
        # The list holds plain dicts, never SDK objects, so what is in memory and
        # what is in the database are the same shape.
        messages.append(journal.remember(message) if journal else memory.to_dict(message))
        if journal:
            journal.mark(turns, tokens)

        if not message.tool_calls:
            result.answer = message.content or ""
            if not quiet:
                ui.answer(result.answer or "(no reply)")
            break

        done = False
        for call in message.tool_calls:
            name = call.function.name
            # Commit the intent before the side effect. A crash between these two
            # lines is the only case a resume cannot decide on its own.
            if journal:
                journal.begin(call.id, name, call.function.arguments)
            output = run_tool(name, call.function.arguments)
            if journal:
                journal.done(call.id, output)
            failed = output.startswith("Error:")

            result.tool_calls.append(name)
            if failed:
                result.errors.append(output)

            if not quiet:
                if name != "finish":
                    ui.tool_call(name, describe(name, call.function.arguments),
                                 summarise(name, output), failed)
                if failed or verbose:
                    ui.tool_detail(output, failed)

            body = {"role": "tool", "tool_call_id": call.id, "content": output}
            messages.append(journal.remember(body) if journal else body)

            if name == "finish" and not failed:
                result.answer = output
                if not quiet:
                    ui.finished(output)
                done = True
        if done:
            break

        if journal:
            before = compact.count(messages)
            if journal.maybe_compact(client, MODEL, messages) and not quiet:
                ui.compacted(before, compact.count(messages))

    result.turns, result.tokens = turns, tokens
    result.seconds = time.monotonic() - started
    if not quiet:
        ui.footer(turns, tokens, result.seconds)
    return result


HELP = """  /help    this
  /clear   forget the conversation, keep the session
  /exit    leave
"""


def status_for(result: RunResult) -> str:
    if result.stopped_reason:
        return memory.STOPPED
    return memory.FINISHED


def open_journal(store, task: str, workspace, messages: list) -> "memory.Journal":
    """Start a run and put what has been said so far on disk, system prompt included."""
    journal = memory.Journal.start(store, task, str(workspace), MODEL)
    for message in messages:
        journal.remember(message)
    return journal


def repl(client, store, messages, workspace, verbose: bool) -> int:
    print("Type a task. /help for commands, /exit to leave.\n")
    journal = None
    while True:
        try:
            line = ui.prompt().strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            if journal:
                journal.close(memory.INTERRUPTED)
            return 0

        if not line:
            continue
        if line in {"/exit", "/quit", "exit", "quit"}:
            print("bye")
            if journal:
                journal.close(memory.FINISHED)
            return 0
        if line == "/help":
            print(HELP)
            continue
        if line == "/clear":
            del messages[1:]
            if journal:
                journal.close(memory.FINISHED)
                journal = None
            print("conversation cleared\n")
            continue

        # A session becomes a run at its first real task, so the run has a name.
        if journal is None:
            journal = open_journal(store, line, workspace, messages)
            print(f"  run {journal.run_id}\n")

        messages.append(journal.remember({"role": "user", "content": line}))
        try:
            run_task(client, messages, verbose, journal=journal)
        except KeyboardInterrupt:
            journal.close(memory.INTERRUPTED)
            print("\ninterrupted")
            return 0
        print()


def resume(client, store, prefix: str, auto_approve: bool, verbose: bool) -> int:
    run, problem = memory.open_run(store, prefix)
    if run is None:
        print(f"\n  {problem}\n")
        return 1

    confine.configure(run.workspace, auto_approve)
    ui.header(run.workspace, run.model)

    journal = memory.Journal.reopen(store, run.id)
    messages = store.live_messages(run.id)
    notes = journal.settle(messages, run_tool)
    if not notes:
        # Nothing was in flight, so give the model somewhere to start from.
        messages.append(journal.remember(
            {"role": "user", "content": "Continue from where you left off."}
        ))
        notes = ["nothing was in flight, continuing"]
    ui.resumed(run.id, run.task, notes)

    try:
        result = run_task(client, messages, verbose, journal=journal)
    except KeyboardInterrupt:
        journal.close(memory.INTERRUPTED)
        print("\ninterrupted")
        return 130
    journal.close(status_for(result), result.stopped_reason, result.answer)
    return 0


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="braze", description="A terminal coding agent.")
    parser.add_argument("task", nargs="?", help="What you want done. Omit for an interactive session.")
    parser.add_argument("-w", "--workspace", default=None,
                        help="Directory the agent may touch. Defaults to the current one.")
    parser.add_argument("-y", "--yes", action="store_true", help="Run commands without asking.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each tool result.")
    parser.add_argument("--runs", action="store_true", help="List past runs and stop.")
    parser.add_argument("--resume", metavar="ID", help="Pick a run back up from its last committed step.")
    parser.add_argument("--budget", metavar="ID", help="Show the token count over time for a run.")
    args = parser.parse_args()

    store = memory.Store()

    if args.runs:
        ui.runs(store.list_runs())
        return 0

    if args.budget:
        run = store.find_run(args.budget)
        if run is None:
            print(f"\n  no run matches {args.budget!r}\n")
            return 1
        print()
        print(memory.sawtooth(store.budget_history(run.id)))
        return 0

    client = OpenAI(api_key=get_api_key())

    if args.resume:
        return resume(client, store, args.resume, args.yes, args.verbose)

    workspace = confine.configure(args.workspace, args.yes)
    ui.header(workspace, MODEL)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if args.task is None:
        return repl(client, store, messages, workspace, args.verbose)

    journal = open_journal(store, args.task, workspace, messages)
    messages.append(journal.remember({"role": "user", "content": args.task}))
    try:
        result = run_task(client, messages, args.verbose, journal=journal)
    except KeyboardInterrupt:
        journal.close(memory.INTERRUPTED)
        print("\ninterrupted")
        return 130
    journal.close(status_for(result), result.stopped_reason, result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
