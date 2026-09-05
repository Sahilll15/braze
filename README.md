# Toolsmith

A terminal coding agent you point at a directory of real code. You give it a
task in English, it reads files, edits them, runs the tests, and keeps going
until they pass.

The catch: it is not written yet. `toolsmith.py` is ten numbered steps and no
implementation. The point of this project is that you write the loop by hand,
against the raw chat-completions API, with no agent framework anywhere. Every
framework you have used is wrapping about fifteen lines, and you do not really
know what those lines do until you have written them and watched them fail.

## Setup

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env      # put an OpenAI-compatible key in it
```

Then open `toolsmith.py` and start at STEP 1.

## The practice repo

`practice-repo/` is a small word-count CLI with a test suite. Six tests, four
pass, two fail because a `--json` flag does not exist yet.

```bash
cd practice-repo && ../venv/bin/python -m pytest -q
# 2 failed, 4 passed
```

That is the target. Your agent is finished when this works without you
touching anything:

```bash
./venv/bin/python toolsmith.py \
  "Add a --json flag to the wc CLI and make the failing tests pass" --yes
```

and `pytest` then reports 6 passed.

The failing tests matter more than they look. An agent that writes code will
happily tell you it succeeded. Tests are a verdict it cannot argue with: either
the process exits 0 or it does not. It is also the loop's whole reason to
exist, because the agent runs the tests, reads the failure, and tries again.

Reset the repo between attempts with `git checkout practice-repo/`.

## Two meanings of "sandbox"

Worth separating, because the word gets used for both and they are not the same
strength of thing.

**Confinement.** Keeping the agent inside one directory, so it cannot read your
SSH keys or write to `/etc`. That is STEP 7, and it is a check inside your own
process. If your path check has a bug, there is nothing behind it. Useful,
weak.

**Isolation.** Running the agent's commands inside a container or a microVM
with no network, a read-only filesystem, and a memory limit, so a successful
escape still lands somewhere that cannot hurt you. That is a real boundary
enforced by the kernel rather than by your `if` statement, and it is a later
project.

This project does confinement. Knowing that is not the strong version is part
of the lesson.

## What this is

Project 01 of a roadmap toward agentic AI engineering. Project 02 gives this
agent memory that survives being killed mid-task.

A finished implementation lives on the `reference` branch. Do not read it until
yours runs, then diff and disagree with it.
