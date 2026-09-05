import os
import subprocess
import sys

from . import confine
from .text import truncate
from .confine import approve

TIMEOUT_SECONDS = 60


def run_command(command: str) -> str:
    """Run a shell command and return its exit code, stdout and stderr."""
    # resolve() cannot help here: a shell string never becomes a Path.
    if not approve(command):
        return "Error: the user declined to run that command. Try another approach."

    # Running under venv/bin/python does not put venv/bin on PATH, so `pytest`
    # is not found and the model works around it instead of using it.
    env = {**os.environ, "PATH": f"{os.path.dirname(sys.executable)}{os.pathsep}{os.environ['PATH']}"}
    try:
        proc = subprocess.run(
            command, shell=True, cwd=confine.WORKSPACE, capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS, env=env,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {TIMEOUT_SECONDS}s: {command!r}"

    parts = [f"exit code: {proc.returncode}"]
    if proc.stdout.strip():
        parts.append(f"stdout:\n{proc.stdout.rstrip()}")
    if proc.stderr.strip():
        parts.append(f"stderr:\n{proc.stderr.rstrip()}")
    return truncate("\n\n".join(parts))
