from .confine import resolve


def write_file(path: str, content: str) -> str:
    """Write content to a file, creating parent directories as needed."""
    target = resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {path} ({len(content.splitlines())} lines)"
