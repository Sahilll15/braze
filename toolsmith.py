"""Toolsmith: a terminal coding agent whose loop you write by hand.

Nothing here is implemented. This file is the map, not the territory.

The finished program should take a task in English, point a model at a
directory of real code, and let it read, edit and run things until the task is
done. No agent framework: you write the message list, the tool schemas, the
dispatch and every stopping rule yourself.

Work top to bottom. Each STEP is a sitting. After each one, run:

    ./venv/bin/python toolsmith.py "..." -v

and see how far it gets. It should get further each time.

A finished version of this file exists on the `reference` branch. Do not look
at it until yours works, then diff and argue with it.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# STEP 1  Say hello to the API
#
# Goal: one request, one reply, no tools. Prove your key works and that you
# know the shape of a response.
#
# - Create an OpenAI client. The key is in .env, load it with python-dotenv.
# - Send messages=[{"role": "user", "content": "..."}] to
#   client.chat.completions.create(model=..., messages=...).
# - Print response.choices[0].message.content.
# - Also print response.choices[0].finish_reason and response.usage. You will
#   care about both of those later.
#
# Stop when you can explain what every field you printed means.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STEP 2  Describe one tool and watch the model ask for it
#
# Goal: the model replies with a request to call a function, not with prose.
#
# - Write a JSON Schema by hand for a single tool, read_file, taking {path}.
#   The API wants: {"type": "function", "function": {"name", "description",
#   "parameters"}} where parameters is the schema.
# - Pass tools=[that] to the same create() call.
# - Ask it something that needs the tool, then print
#   response.choices[0].message.tool_calls.
#
# Notice: finish_reason is now "tool_calls", not "stop". The model did not do
# anything. It asked you to. Nothing runs unless you run it.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STEP 3  Actually run it and hand the result back
#
# Goal: one full round trip. Request, run, reply.
#
# - Implement read_file for real. Return a string.
# - Append the assistant message to your messages list, unchanged.
# - Then append {"role": "tool", "tool_call_id": <the call's id>,
#   "content": <your string>} for each call.
# - Call create() again with the longer messages list and print what comes back.
#
# The tool_call_id has to match or the API rejects the conversation. This is
# the moment the "conversation" stops being a chat and becomes a transcript
# you are assembling.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STEP 4  Wrap it in a loop
#
# Goal: the agent. Everything before this was one turn.
#
#     while True:
#         response = create(messages, tools)
#         append the assistant message
#         if no tool_calls: return its content
#         for each call: run it, append a tool message
#
# That is the whole ReAct loop. It is about fifteen lines and it is the thing
# every framework is wrapping.
#
# Try it and watch it run forever, or stop early, or call the same tool nine
# times. That is Step 5's problem.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STEP 5  Make it stop
#
# Goal: three limits, enforced by your code.
#
# - A turn cap. A wall-clock cap. A token budget, summed from response.usage.
# - Check all three BEFORE each request, not after. Checking after means you
#   already paid for the call that broke the budget.
# - Raise your own exception and catch it in main(), so a stopped run prints
#   why it stopped.
#
# Do not put any of this in the prompt. "Please stop after 25 steps" is a
# wish. A counter is a guarantee.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STEP 6  The rest of the tools
#
# Goal: enough tools to do real work. write_file, list_dir, grep,
# run_command, finish.
#
# - finish is a tool that does nothing except end the loop. Giving the model an
#   explicit way to say "done" is much better than guessing from prose.
# - run_command needs a timeout, or one bad command hangs the whole agent.
# - Writing five more JSON Schemas by hand will annoy you. Good. That is what
#   Step 8 fixes.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STEP 7  Keep it inside the directory
#
# Goal: the agent cannot touch anything outside the workspace you gave it.
#
# - Resolve every path against the workspace root and reject it if the result
#   is not underneath. (workspace / path).resolve(), then check the parents.
# - Try to break your own check: "../../.ssh/id_rsa", an absolute path, a
#   symlink pointing out.
# - Make run_command ask for your approval before running, unless --yes.
#
# This is one meaning of the word "sandbox", and it is the weak one. It is a
# check inside your process, which means a bug in your check is the whole
# defence gone. Project 06 replaces it with a real boundary.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STEP 8  Generate the schemas instead of writing them
#
# Goal: one definition per tool.
#
# - Define each tool's arguments as a pydantic BaseModel.
# - model_json_schema() gives you the parameters. The class docstring gives
#   you the description.
# - model_validate_json() on the way back catches the model inventing an
#   argument, and gives you a readable error to hand it.
#
# Now a tool cannot drift from its own schema, because there is only one of it.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STEP 9  Make failures readable
#
# Goal: the model recovers from a bad tool call instead of giving up.
#
# - Never hand back a raw traceback. Say what went wrong and what to try:
#   "no such file: 'wc.py'. Use list_dir to see what exists."
# - Truncate long output in the middle so the head and the tail both survive.
#   A 200KB file dumped into the transcript costs money and teaches nothing.
# - Number the lines in read_file so the model can refer to them.
#
# The tool result is the model's entire view of what happened. If it is
# unreadable, the model is guessing.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STEP 10  Make it watchable
#
# Goal: you can see what the model saw.
#
# - A -v flag that dumps the raw messages list every turn.
# - One line per tool call as it happens, so a run is not a silent pause.
# - Print the turn, token and time totals at the end.
#
# Reading the transcript is the only real debugging tool you get. Every
# "why did it do that" is answered in there.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# THE TEST
#
# practice-repo/ is a small word-count CLI with six tests. Four pass. Two fail,
# because there is no --json flag yet.
#
#     cd practice-repo && ../venv/bin/python -m pytest -q
#
# You are done when this finishes on its own, and pytest then passes 6/6:
#
#     ./venv/bin/python toolsmith.py \
#       "Add a --json flag to the wc CLI and make the failing tests pass" --yes
#
# Failing tests are the point. They are a task with an answer the agent cannot
# talk its way around: either pytest exits 0 or it does not.
#
# Reset between attempts:  git checkout practice-repo/
# ---------------------------------------------------------------------------


def main() -> int:
    raise NotImplementedError("Start at STEP 1.")


if __name__ == "__main__":
    raise SystemExit(main())
