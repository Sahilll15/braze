"""Wrap text at a column width, without breaking words."""

from __future__ import annotations


def wrap(text: str, width: int = 40) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines
