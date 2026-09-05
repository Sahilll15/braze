"""A small word-count CLI. Deliberately missing a feature, for the agent to add."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def count(text: str) -> dict[str, int]:
    return {
        "lines": len(text.splitlines()),
        "words": len(text.split()),
        "chars": len(text),
    }


def format_counts(name: str, counts: dict[str, int]) -> str:
    return f"{counts['lines']:>8}{counts['words']:>8}{counts['chars']:>8}  {name}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wc", description="Count lines, words and characters.")
    parser.add_argument("--json", action="store_true", help="Print counts as a JSON array.")
    parser.add_argument("paths", nargs="+", help="Files to count.")
    args = parser.parse_args(argv)

    exit_code = 0
    json_payload = []
    for path in args.paths:
        file = Path(path)
        if not file.is_file():
            print(f"wc: {path}: no such file", file=sys.stderr)
            exit_code = 1
            continue

        counts = count(file.read_text(encoding="utf-8"))
        if args.json:
            json_payload.append({"name": path, **counts})
        else:
            print(format_counts(path, counts))

    if args.json:
        print(json.dumps(json_payload))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
