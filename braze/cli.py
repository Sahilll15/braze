import argparse
import json
import time

from dotenv import load_dotenv
from openai import OpenAI

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


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="braze", description="A terminal coding agent.")
    parser.add_argument("task", help="What you want done.")
    parser.add_argument("-w", "--workspace", default=None,
                        help="Directory the agent may touch. Defaults to the current one.")
    parser.add_argument("-y", "--yes", action="store_true", help="Run commands without asking.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each tool result.")
    args = parser.parse_args()

    workspace = confine.configure(args.workspace, args.yes)
    print(f"braze  ·  {workspace}  ·  {MODEL}\n")

    client = OpenAI()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": args.task},
    ]

    turns = 0
    tokens = 0
    started = time.monotonic()

    while True:
        if turns >= MAX_TURNS:
            print(f"stopped: hit the turn cap ({MAX_TURNS})")
            break
        if time.monotonic() - started >= MAX_SECONDS:
            print(f"stopped: hit the time cap ({MAX_SECONDS}s)")
            break
        if tokens >= MAX_TOKENS:
            print(f"stopped: hit the token cap ({MAX_TOKENS})")
            break

        turns += 1
        completion = client.chat.completions.create(
            model=MODEL, tools=TOOL_SCHEMAS, messages=messages,
        )
        tokens += completion.usage.total_tokens

        message = completion.choices[0].message
        messages.append(message)

        if not message.tool_calls:
            print(message.content)
            break

        done = False
        for call in message.tool_calls:
            print(f"  -> {call.function.name} {call.function.arguments[:90]}")
            result = run_tool(call.function.name, call.function.arguments)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

            if args.verbose or result.startswith("Error:"):
                print(f"     {result[:400]}")

            if call.function.name == "finish" and not result.startswith("Error:"):
                print(f"\n{result}")
                done = True
        if done:
            break

    print(f"\n{turns} turns, {tokens} tokens, {time.monotonic() - started:.1f}s")
    return 0
