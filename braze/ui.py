"""Terminal presentation.

Two rules drive everything here. Body text never gets a foreground colour, so
it inherits the terminal's own and stays readable on light and dark alike.
And nothing is conveyed by colour alone: every state has a glyph too.
"""

import itertools
import textwrap
import shutil
import sys
import threading
import time

WIDTH = min(shutil.get_terminal_size((80, 24)).columns, 88)

# Mid-tone hues only. Anything near-black or near-white disappears on one theme.
DIM = "\033[38;5;244m"
RULE = "\033[38;5;240m"
ACCENT = "\033[38;5;208m"
TOOL = "\033[38;5;74m"
OK = "\033[38;5;71m"
ERR = "\033[38;5;167m"
BOLD = "\033[1m"
OFF = "\033[0m"

CALL = "▸"
FAIL = "✗"
DONE = "✓"


def _out(s: str = "") -> None:
    print(s, flush=True)


def rule() -> None:
    _out(f"{RULE}{'─' * WIDTH}{OFF}")


def header(workspace, model: str) -> None:
    _out()
    _out(f"  {ACCENT}{BOLD}braze{OFF}  {DIM}{workspace}{OFF}")
    _out(f"  {DIM}{model}{OFF}")
    rule()


def prompt() -> str:
    return input(f"\n  {ACCENT}{BOLD}>{OFF} ")


def tool_call(name: str, detail: str, result_note: str = "", failed: bool = False) -> None:
    """One scannable line per call: glyph, name, what it acted on, what came back."""
    glyph = f"{ERR}{FAIL}{OFF}" if failed else f"{TOOL}{CALL}{OFF}"
    left = f"  {glyph} {name} {DIM}{detail}{OFF}"
    if not result_note:
        _out(left)
        return
    # Visible length ignores the escape sequences, so pad against that.
    visible = len(f"  {CALL} {name} {detail}")
    pad = max(WIDTH - visible - len(result_note) - 2, 1)
    colour = ERR if failed else DIM
    _out(f"{left}{' ' * pad}{colour}{result_note}{OFF}")


def tool_detail(text: str, failed: bool = False) -> None:
    colour = ERR if failed else DIM
    for line in text.splitlines()[:12]:
        _out(f"      {colour}{line[:WIDTH - 6]}{OFF}")


def answer(text: str) -> None:
    """Prose gets no colour. That is deliberate."""
    _out()
    for para in text.split("\n"):
        if not para.strip():
            _out()
            continue
        # Fenced code and list items keep their own shape; only prose is wrapped.
        if para.lstrip().startswith(("```", "- ", "* ", "|")) or para.startswith("    "):
            _out(f"  {para}")
            continue
        for line in textwrap.wrap(para, width=WIDTH - 4):
            _out(f"  {line}")


def finished(summary: str) -> None:
    _out()
    lines = textwrap.wrap(summary, width=WIDTH - 4)
    _out(f"  {OK}{DONE}{OFF} {lines[0] if lines else ''}")
    for line in lines[1:]:
        _out(f"    {line}")


def stopped(reason: str) -> None:
    _out()
    _out(f"  {ERR}{FAIL} {reason}{OFF}")


def footer(turns: int, tokens: int, seconds: float) -> None:
    rule()
    _out(f"  {DIM}{turns} turns  ·  {tokens:,} tokens  ·  {seconds:.1f}s{OFF}")


class Spinner:
    """Feedback while the API call blocks. Anything past ~300ms needs one."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str = "thinking"):
        self.label = label
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        if sys.stdout.isatty():
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def _spin(self):
        started = time.monotonic()
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                return
            elapsed = time.monotonic() - started
            sys.stdout.write(f"\r  {DIM}{frame} {self.label} {elapsed:.0f}s{OFF}\033[K")
            sys.stdout.flush()
            time.sleep(0.08)
