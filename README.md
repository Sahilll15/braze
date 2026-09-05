# Toolsmith

A terminal coding agent that reads, edits and runs code in a real repository. The
ReAct loop is written by hand against the raw chat-completions API. There is no
agent framework anywhere in this project, which is the whole point: the message
list, the tool schemas, the dispatch and every termination rule are visible in
one file you can read in a sitting.

```
$ python toolsmith.py "Add a --json flag to the wc CLI and make the failing tests pass" --yes

→ run_command {"command":"pytest -q","reason":"run tests to see failures"}
→ read_file   {"path":"wc.py","start_line":1,"max_lines":400}
→ read_file   {"path":"test_wc.py","start_line":1,"max_lines":400}
→ write_file  {"path":"wc.py", ...}
→ run_command {"command":"pytest -q","reason":"run full test suite"}
→ finish      {"summary":"Added --json flag ... all 6 tests passed."}

8 turns, 22320 tokens, 31.1s
```

## Running it

```bash
python -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env      # then put an OpenAI-compatible key in it
./venv/bin/python toolsmith.py "your task here"
```

The workspace defaults to `sandbox/`, a small word-count CLI with a test suite
where two tests fail because a `--json` flag does not exist yet. It is a real
task with a real pass or fail signal, which makes it a much better target than a
toy prompt.

Useful flags:

| Flag | What it does |
|---|---|
| `-w, --workspace` | The only directory the agent may touch |
| `-v, --verbose` | Dump the raw message list every turn |
| `-y, --yes` | Run shell commands without asking |
| `--max-iterations` | Turn cap, default 25 |
| `--max-seconds` | Wall-clock cap, default 300 |
| `--max-tokens` | Token cap, default 200,000 |

`TOOLSMITH_BASE_URL` points at any OpenAI-compatible provider, so OpenRouter and
Groq work without a code change.

## The six tools

`read_file`, `write_file`, `list_dir`, `grep`, `run_command`, `finish`.

Each one's arguments are a pydantic model whose docstring becomes the tool
description and whose `model_json_schema()` becomes the parameters the API sees.
One definition, no schema kept in sync by hand.

Every path is resolved against the workspace root and refused if it escapes.
`run_command` asks for approval unless you pass `--yes`.

## Three things worth knowing

**Termination is enforced in code, not asked for in the prompt.** A turn cap, a
wall-clock cap and a token budget, all checked *before* each model call rather
than after, because checking after has already spent the money. The interesting
failure is not the run that crashes, it is the run that ends successfully having
done nothing.

**A tool result is the entire view the model gets of what happened.** Results are
truncated in the middle so the head and the tail survive, errors come back as
readable sentences that say what to do next rather than as stack traces, and
`read_file` numbers its lines so the model can refer to them.

**The environment the agent runs commands in is part of the tool design.** The
first working run took 10 turns and left a stray file behind, because `pytest`
was not on `PATH` inside `run_command`: launching via `venv/bin/python` does not
put `venv/bin` on the path. The model got a legible "command not found", decided
pytest was unavailable, wrote its own test harness, and verified against that
instead. Prepending the running interpreter's directory to `PATH` fixed it, and
the same task then took 8 turns with the real test suite and no leftovers. The
bug was in the tool, not the prompt.

## What this is

Project 01 of a roadmap toward agentic AI engineering. The next one gives this
agent memory that survives being killed mid-task.
