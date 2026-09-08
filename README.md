# braze

A terminal coding agent. You give it a task in English, it reads your files,
edits them, runs your tests, and keeps going until they pass.

The ReAct loop is written by hand against the raw chat-completions API. No agent
framework anywhere. Everything a framework would do for you, the transcript, the
tool schemas, the dispatch, the stopping rules, is visible in `braze/cli.py`.

<video src="https://github.com/Sahilll15/braze/raw/main/docs/demo.mp4" controls muted playsinline width="900"></video>

![braze solving a task](docs/demo.gif)

<sub>Two failing tests, one sentence of instruction, seven turns.
The player above needs JavaScript, the gif does not.
[The tape that shot it](docs/demo.tape) re-records the demo whenever the interface changes.</sub>

## Install

```bash
python3 -m venv venv
./venv/bin/pip install -e .
cp .env.example .env      # put an OpenAI key in it
```

The first run asks for your OpenAI key and saves it to `~/.braze/config.json`,
owner-readable only. No key ships with this package. `OPENAI_API_KEY` in the
environment wins over the config file if both are set.

Then from any directory:

```bash
braze                        # interactive session
braze "your task here"       # one task and exit
```

In a session, the conversation carries across turns, so you can follow up with
"why did you do that" or "undo the second change". `/clear` forgets the
conversation, `/exit` leaves.

| Flag | What it does |
|---|---|
| `-w, --workspace` | Directory the agent may touch. Defaults to the current one. |
| `-y, --yes` | Run shell commands without asking. |
| `-v, --verbose` | Print every tool result, not just errors. |
| `--runs` | List past runs and which of them can be picked back up. |
| `--resume ID` | Continue a run from its last committed step. |
| `--budget ID` | Show that run's token count over time. |

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

## It survives being closed

Close the laptop, lose the connection, `kill -9` the process. The run is still
there.

```
$ braze --runs

  id            when                  status        task
  ───────────────────────────────────────────────────────────────────
  40a9f6c8c2b9  2026-09-08 15:54:12   ▸ running     the tests in test_orders.py f...
  11c31e6d0219  2026-09-08 15:53:43   ✓ finished    list the files here

$ braze --resume 40a9f6

  resuming 40a9f6c8c2b9
  ▸ nothing was in flight, continuing
  ▸ edit_file money.py                                    -3 +14 lines
  ▸ run_command pytest -q                                       exit 0
  ✓ Fixed the failing order tests. Verified with pytest -q: 6 passed.
```

Every message and every tool call goes into SQLite in WAL mode at
`~/.braze/runs.db` as it happens. Nothing is buffered until the end, because a
process that dies never reaches the end.

### The part that is actually hard

Saving the transcript is easy. Knowing what to do with the tool call that was in
flight when you died is not.

The step row is committed **before** the tool runs and updated after, so a
resume can tell "I was about to do that" apart from "I did that". What it cannot
tell is whether a step marked `started` got far enough to change anything, and
that question has no single right answer. Re-running it may repeat a side
effect. Skipping it may lose one. So each tool declares which it is:

| Tool | On resume | Why |
|---|---|---|
| `read_file`, `list_dir`, `grep` | run it again | Reads change nothing. |
| `write_file` | run it again | Writing the same bytes twice is the same as once. |
| `edit_file` | check, then decide | Hash the file before the call. If it still matches, the edit never landed, so run it. If it changed, it landed. |
| `run_command` | never repeat it | A shell command can do anything. Say so and let the model check. |

That last row is the honest one. `braze` will not re-run your deploy script on a
whim:

```
  resuming 43e2da2dab2b
  ▸ run_command: cannot be repeated safely, reported to the model
  ▸ run_command test -f deployed.txt ...                        exit 0

  The command was interrupted and may or may not have completed. I checked
  for `deployed.txt`, and it does not appear to exist.
```

The agent gets told it does not know, and goes and finds out. That is better
than a system that guesses confidently in either direction.

## Context that does not run out

Past 60 percent of the window, the oldest turns are summarised into one note and
dropped from what the model sees. The database keeps them, so what is lost is
the context, never the record.

```
$ braze --budget ada638

    7  ################################            5,243
    8  ####################################        5,853 -> 4,149
    9  ############################                4,544
   10  ##############################              4,923 -> 3,484
   11  ######################                      3,569
   ...
   19  ########################################    6,589 -> 5,513

  peak 6,589 tokens, window 8,000, compacting above 4,800
```

Two rules keep that sawtooth from becoming a straight line of wasted calls.

Compaction aims for 35 percent, not 59. Landing just under the trigger means
compacting again next turn, and paying for a summary every single turn. The
first version of this did exactly that.

A summary that is bigger than what it replaces is thrown away. Four short turns
condense into a note that costs more tokens than the turns did, and the first
version shipped that too: `compacted 4,079 → 4,174 tokens`. The saving is now
computed before anything is dropped.

An assistant message and its tool results are never separated, because the API
rejects a tool result whose matching call is gone. Compaction moves whole groups
or nothing.

## practice-repo/

A small word-count CLI with six tests, two of which fail because there is no
`--json` flag. A task with a verdict the agent cannot argue with.

Reset it between runs with `git checkout practice-repo/`.
