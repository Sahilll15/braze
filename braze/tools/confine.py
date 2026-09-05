from pathlib import Path

# Set once by toolsmith.py before any tool runs.
WORKSPACE = Path.cwd()
AUTO_APPROVE = False


def configure(workspace: str | None, auto_approve: bool) -> Path:
    global WORKSPACE, AUTO_APPROVE
    WORKSPACE = Path(workspace or Path.cwd()).resolve()
    AUTO_APPROVE = auto_approve
    return WORKSPACE


def resolve(path: str) -> Path:
    """Resolve a path against the workspace, refusing anything that escapes it.

    The check runs after resolving because pathlib lets an absolute right-hand
    side win: WORKSPACE / "/etc/passwd" is simply /etc/passwd.
    """
    target = (WORKSPACE / path).resolve()
    if target != WORKSPACE and WORKSPACE not in target.parents:
        raise PermissionError(f"path escapes the workspace: {path!r}")
    return target


def approve(action: str) -> bool:
    if AUTO_APPROVE:
        return True
    print(f"\n  run this?\n    {action}")
    return input("  [y/N] ").strip().lower() in {"y", "yes"}
