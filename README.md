# Toolsmith

A terminal coding agent. Written from scratch.

## Setup

Already done, but for the record:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

`.env` holds the API key. `.env.example` shows the shape.

## Running

```bash
./venv/bin/python toolsmith.py
```

## practice-repo/

A small word-count CLI with a test suite. Six tests, four pass, two fail
because there is no `--json` flag.

```bash
cd practice-repo && ../venv/bin/python -m pytest -q
```

That is the target. The agent works when it can add the flag and get all six
passing on its own.

Reset it between attempts with `git checkout practice-repo/`.
