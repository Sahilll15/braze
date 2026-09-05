import re

from .text import truncate
from .confine import resolve

SKIP = {".git", "venv", "__pycache__", ".pytest_cache", "node_modules"}


def grep(pattern: str, path: str = ".", max_results: int = 60) -> str:
    """Search files for a regular expression and return matching lines."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return f"Error: invalid regular expression {pattern!r}: {exc}"

    root = resolve(path)
    if not root.exists():
        return f"Error: path '{path}' does not exist."

    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    hits = []
    for file in files:
        if SKIP & set(file.parts):
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if compiled.search(line):
                hits.append(f"{file.relative_to(resolve('.'))}:{number}: {line.strip()}")
                if len(hits) >= max_results:
                    return truncate("\n".join(hits)) + f"\n[stopped at {max_results} matches]"

    return truncate("\n".join(hits)) if hits else f"no matches for {pattern!r}"
