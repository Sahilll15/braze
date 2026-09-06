"""Score braze against the task set.

Each task runs in a throwaway copy of its fixture, so one run can never see
another's edits. Then a checker reads the filesystem and decides pass or fail.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from openai import OpenAI

from braze.cli import MODEL, SYSTEM_PROMPT, run_task
from braze.config import get_api_key
from braze.tools import confine
from eval.tasks import FIXTURES, TASKS, RunSummary

# gpt-5.5 list price per million tokens, for a rough cost per task.
# Input and output are not billed the same, but usage only gives us a total
# here, so treat this as an order of magnitude rather than an invoice.
USD_PER_MILLION_TOKENS = 1.25

RUNS = Path(__file__).parent / "runs"
DIM, OK, ERR, BOLD, OFF = "\033[38;5;244m", "\033[38;5;71m", "\033[38;5;167m", "\033[1m", "\033[0m"


def run_one(task, client) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"{task.fixture}__") as tmp:
        workspace = Path(tmp) / task.fixture
        shutil.copytree(FIXTURES / task.fixture, workspace)
        confine.configure(str(workspace), auto_approve=True)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task.prompt},
        ]
        started = time.monotonic()
        try:
            result = run_task(client, messages, verbose=False, quiet=True)
            crashed = ""
        except Exception as exc:
            crashed = f"{type(exc).__name__}: {exc}"
            result = None

        if result is None:
            return {
                "id": task.id, "fixture": task.fixture, "passed": False,
                "note": f"the harness crashed: {crashed}",
                "turns": 0, "tokens": 0, "seconds": round(time.monotonic() - started, 1),
                "tool_calls": [], "errors": [], "stopped_reason": "crashed",
            }

        summary = RunSummary(
            turns=result.turns, tokens=result.tokens, seconds=result.seconds,
            tool_calls=result.tool_calls, answer=result.answer,
            stopped_reason=result.stopped_reason,
        )
        # The checker runs while the copy still exists, and never sees the
        # agent's own claim about whether it succeeded.
        try:
            passed, note = task.check(workspace, summary)
        except Exception as exc:
            passed, note = False, f"the checker raised: {type(exc).__name__}: {exc}"

        return {
            "id": task.id, "fixture": task.fixture, "passed": passed, "note": note,
            "turns": result.turns, "tokens": result.tokens,
            "seconds": round(result.seconds, 1),
            "tool_calls": result.tool_calls,
            "errors": result.errors[:3],
            "stopped_reason": result.stopped_reason,
        }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Score braze against the task set.")
    parser.add_argument("-k", "--only", help="Run only tasks whose id contains this.")
    parser.add_argument("-n", "--repeat", type=int, default=1,
                        help="Run each task this many times. Agents are not deterministic.")
    args = parser.parse_args()

    tasks = [t for t in TASKS if not args.only or args.only in t.id]
    client = OpenAI(api_key=get_api_key())

    print(f"\n  {BOLD}braze eval{OFF}  {DIM}{len(tasks)} tasks x {args.repeat}  ·  {MODEL}{OFF}\n")
    rows = []
    for task in tasks:
        for attempt in range(args.repeat):
            label = task.id if args.repeat == 1 else f"{task.id}#{attempt + 1}"
            print(f"  {DIM}{label:<20} running...{OFF}", end="\r", flush=True)
            row = run_one(task, client)
            row["attempt"] = attempt + 1
            rows.append(row)
            mark = f"{OK}pass{OFF}" if row["passed"] else f"{ERR}FAIL{OFF}"
            print(f"  {label:<20} {mark}  {DIM}{row['turns']:>2} turns  "
                  f"{row['tokens']:>6,} tok  {row['seconds']:>5.1f}s  {row['note'][:44]}{OFF}")

    passed = sum(r["passed"] for r in rows)
    tokens = sum(r["tokens"] for r in rows)
    turns = [r["turns"] for r in rows if r["passed"]]
    cost = tokens / 1_000_000 * USD_PER_MILLION_TOKENS

    print(f"\n  {BOLD}{passed}/{len(rows)} passed{OFF}"
          f"  {DIM}·  {tokens:,} tokens  ·  ${cost:.3f}"
          f"  ·  median {sorted(turns)[len(turns) // 2] if turns else 0} turns on a pass{OFF}")
    if passed:
        print(f"  {DIM}${cost / passed:.4f} per passing task{OFF}")

    RUNS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    path = RUNS / f"{stamp}.json"
    path.write_text(json.dumps({
        "model": MODEL, "at": stamp, "passed": passed, "total": len(rows),
        "tokens": tokens, "usd": round(cost, 4), "rows": rows,
    }, indent=2) + "\n")
    print(f"  {DIM}{path}{OFF}\n")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
