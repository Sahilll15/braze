"""Order totals, built on money.py."""

from __future__ import annotations

from money import apply_discount, format_rupees, to_paise


def line_total(unit_price: str, quantity: int) -> int:
    return to_paise(unit_price) * quantity


def order_total(lines: list[tuple[str, int]], discount_percent: int = 0) -> str:
    """Sum the lines, apply the discount, return a rupee string."""
    subtotal = sum(line_total(price, qty) for price, qty in lines)
    return format_rupees(apply_discount(subtotal, discount_percent))
