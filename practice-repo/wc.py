"""A small word-count CLI. Deliberately missing features, for the agent to fix."""

from __future__ import annotations

import argparse
import sys
import json
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
    parser.add_argument("--json", action="store_true", help="Emit JSON array of count objects.")
    parser.add_argument("paths", nargs="+", help="Files to count.")
    args = parser.parse_args(argv)

    exit_code = 0

    if args.json:
        results: list[dict[str, object]] = []
        for path in args.paths:
            file = Path(path)
            if not file.is_file():
                print(f"wc: {path}: no such file", file=sys.stderr)
                exit_code = 1
                continue
            counts = count(file.read_text(encoding="utf-8"))
            results.append({"name": path, "lines": counts["lines"], "words": counts["words"], "chars": counts["chars"]})
        print(json.dumps(results))
        return exit_code

    for path in args.paths:
        file = Path(path)
        if not file.is_file():
            print(f"wc: {path}: no such file", file=sys.stderr)
            exit_code = 1
            continue
        print(format_counts(path, count(file.read_text(encoding="utf-8"))))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
