"""Parse a semantic version string."""

from __future__ import annotations


def parse_version(text: str) -> tuple[int, ...]:
    """Turn '1.2.3' into (1, 2, 3). Missing parts are left off."""
    return tuple(int(part) for part in text.split("."))
