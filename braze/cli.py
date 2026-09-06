import argparse
import json
from dataclasses import dataclass, field
import readline  # noqa: F401  gives input() arrow-key history
import time

from dotenv import load_dotenv
from openai import OpenAI

from . import ui
from .config import get_api_key
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


def run_task(client, messages, verbose: bool, quiet: bool = False) -> RunResult:
    """Drive one task to completion, appending to `messages` in place."""
    result = RunResult()
    turns = 0
    tokens = 0
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
        with ui.Spinner(enabled=not quiet):
            completion = client.chat.completions.create(
                model=MODEL, tools=TOOL_SCHEMAS, messages=messages,
            )
        tokens += completion.usage.total_tokens

        message = completion.choices[0].message
        messages.append(message)

        if not message.tool_calls:
            result.answer = message.content or ""
            if not quiet:
                ui.answer(result.answer or "(no reply)")
            break

        done = False
        for call in message.tool_calls:
            name = call.function.name
            output = run_tool(name, call.function.arguments)
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

            messages.append({"role": "tool", "tool_call_id": call.id, "content": output})

            if name == "finish" and not failed:
                result.answer = output
                if not quiet:
                    ui.finished(output)
                done = True
        if done:
            break

    result.turns, result.tokens = turns, tokens
    result.seconds = time.monotonic() - started
    if not quiet:
        ui.footer(turns, tokens, result.seconds)
    return result


HELP = """  /help    this
  /clear   forget the conversation, keep the session
  /exit    leave
"""


def repl(client, messages, verbose: bool) -> int:
    print("Type a task. /help for commands, /exit to leave.\n")
    while True:
        try:
            line = ui.prompt().strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return 0

        if not line:
            continue
        if line in {"/exit", "/quit", "exit", "quit"}:
            print("bye")
            return 0
        if line == "/help":
            print(HELP)
            continue
        if line == "/clear":
            del messages[1:]
            print("conversation cleared\n")
            continue

        messages.append({"role": "user", "content": line})
        try:
            run_task(client, messages, verbose)
        except KeyboardInterrupt:
            print("\ninterrupted")
        print()


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="braze", description="A terminal coding agent.")
    parser.add_argument("task", nargs="?", help="What you want done. Omit for an interactive session.")
    parser.add_argument("-w", "--workspace", default=None,
                        help="Directory the agent may touch. Defaults to the current one.")
    parser.add_argument("-y", "--yes", action="store_true", help="Run commands without asking.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each tool result.")
    args = parser.parse_args()

    workspace = confine.configure(args.workspace, args.yes)
    ui.header(workspace, MODEL)

    client = OpenAI(api_key=get_api_key())
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if args.task is None:
        return repl(client, messages, args.verbose)

    messages.append({"role": "user", "content": args.task})
    run_task(client, messages, args.verbose)
    return 0

