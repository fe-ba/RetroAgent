"""Amounts of money with two decimals."""

from decimal import Decimal

CENT = Decimal("0.01")


def money(value) -> Decimal:
    """Return value as an amount with two decimals."""
    return Decimal(str(value)).quantize(CENT)


def as_text(amount) -> str:
    return f"{money(amount):.2f}"
