from .confine import resolve
from .text import truncate


def read_file(file_path: str, start_line: int = 1, max_lines: int = 400) -> str:
    """Read a text file inside the workspace, with line numbers."""
    target = resolve(file_path)
    if not target.exists():
        return f"Error: no such file: '{file_path}'. Use list_dir to see what exists."
    if target.is_dir():
        return f"Error: '{file_path}' is a directory. Use list_dir for that."

    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(start_line - 1, 0)
    window = lines[start : start + max_lines]
    body = "\n".join(f"{start + i + 1:>5}  {line}" for i, line in enumerate(window))
    if start + len(window) < len(lines):
        body += f"\n\n[showing lines {start + 1}-{start + len(window)} of {len(lines)}]"
    return truncate(body)
