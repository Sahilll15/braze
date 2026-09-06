import money
from money import apply_discount, to_paise
from orders import line_total, order_total


def test_to_paise_handles_single_decimal_place():
    assert to_paise("12.5") == 1250


def test_line_total():
    assert line_total("12.50", 3) == 3750


def test_discount_rounds_down():
    assert apply_discount(1000, 33) == 670


def test_order_total_without_discount():
    assert order_total([("12.50", 2), ("4.25", 1)]) == "29.25"


def test_money_exposes_discounted_line():
    """money.py should own the per-line discount, not orders.py."""
    assert hasattr(money, "discounted_line")
    assert money.discounted_line(1000, 3, 10) == 2700


def test_discount_applies_per_line_not_to_the_subtotal():
    """Each line is discounted and rounded down on its own, then summed.

    Subtotal-then-discount gives 26.32 here. Per-line gives 26.30, because
    the 4.25 line loses its own fraction before the sum.
    """
    assert order_total([("12.50", 2), ("4.25", 1)], discount_percent=10) == "26.30"
