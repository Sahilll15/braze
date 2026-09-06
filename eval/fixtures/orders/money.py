"""Money handling. Amounts are integer paise, never floats."""

from __future__ import annotations


def to_paise(rupees: str) -> int:
    """Parse a rupee string like '12.50' into integer paise."""
    whole, _, frac = rupees.partition(".")
    return int(whole) * 100 + int(frac.ljust(2, "0")[:2] or 0)


def format_rupees(paise: int) -> str:
    return f"{paise // 100}.{paise % 100:02d}"


def apply_discount(paise: int, percent: int) -> int:
    """Take a whole-number percentage off. Rounds down, in the customer's favour."""
    return paise - (paise * percent // 100)
