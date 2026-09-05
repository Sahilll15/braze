from .confine import resolve


def list_dir(path: str = ".") -> str:
    """List the files and directories at a path."""
    dir_path = resolve(path)
    if not dir_path.exists():
        return f"Error: path '{path}' does not exist."
    if not dir_path.is_dir():
        return f"Error: path '{path}' is a file, not a directory."

    entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name))
    if not entries:
        return f"{path} is empty"
    return "\n".join(f"{'dir ' if e.is_dir() else 'file'}  {e.name}" for e in entries)
