# braze

A terminal coding agent. You give it a task in English, it reads your files,
edits them, runs your tests, and keeps going until they pass.

The ReAct loop is written by hand against the raw chat-completions API. No agent
framework anywhere. Everything a framework would do for you, the transcript, the
tool schemas, the dispatch, the stopping rules, is visible in `braze/cli.py`.

```
$ cd practice-repo
$ braze "add a --json flag to the wc CLI so the failing tests pass, then run the tests" --yes

braze  ·  /Users/sahil/Desktop/Projects/toolsmith/practice-repo  ·  gpt-5.5

  -> list_dir    {"path":"."}
  -> read_file   {"file_path":"wc.py"}
  -> read_file   {"file_path":"test_wc.py"}
  -> edit_file   {"path":"wc.py","old_text":"import argparse\nimport sys..."}
  -> edit_file   {"path":"wc.py","old_text":"    parser = argparse.Argum..."}
  -> run_command {"command":"pytest -q"}
  -> finish      {"summary":"Added a documented --json flag..."}

7 turns, 10193 tokens, 13.4s
```

## Install

```bash
python3 -m venv venv
./venv/bin/pip install -e .
cp .env.example .env      # put an OpenAI key in it
```

Then from any directory:

```bash
braze "your task here"
```

| Flag | What it does |
|---|---|
| `-w, --workspace` | Directory the agent may touch. Defaults to the current one. |
| `-y, --yes` | Run shell commands without asking. |
| `-v, --verbose` | Print every tool result, not just errors. |

## The seven tools

`read_file`, `write_file`, `edit_file`, `list_dir`, `grep`, `run_command`, `finish`.

`edit_file` replaces one exact block of text and refuses if the match is not
unique. That matters more than it sounds: rewriting a whole file means the model
regenerates code it only skimmed, and quietly drops things.

`finish` does nothing except end the run. An explicit way to say "done" beats
inferring it from silence.

## Three things it gets right

**Termination is enforced in code.** A turn cap, a wall-clock cap and a token
budget, all checked before each request rather than after, because checking
after means you already paid for the call that broke the budget. None of it is
in the prompt. "Please stop after 25 steps" is a wish; a counter is a guarantee.

**Nothing a tool does can kill the run.** Every failure comes back as a sentence
the model can act on. `no such file: 'wc.py'. Use list_dir to see what exists.`
gets you a correct next call. A traceback gets you a dead process. That rule
lives in one place, `run_tool`, so no individual tool can forget it.

**Paths are confined to the workspace.** Every filesystem tool routes through
`resolve()`, which resolves first and checks second, because `WORKSPACE /
"/etc/passwd"` is just `/etc/passwd`. Symlinks pointing out are caught too.

And one thing it does not. `run_command` hands a string to a shell, so no path
check applies and `cat ../../.ssh/id_rsa` walks straight out. The only gate
there is asking you first, and `--yes` removes it. Real isolation means a
container with no network and no access to your home directory. That is a
different project.

## practice-repo/

A small word-count CLI with six tests, two of which fail because there is no
`--json` flag. A task with a verdict the agent cannot argue with.

Reset it between runs with `git checkout practice-repo/`.
