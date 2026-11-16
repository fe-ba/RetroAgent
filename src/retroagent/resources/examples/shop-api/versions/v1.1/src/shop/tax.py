"""Value added tax."""

from decimal import Decimal

from shop.money import money

VAT_RATE = Decimal("0.19")


def tax_amount(amount: Decimal) -> Decimal:
    return money(amount * VAT_RATE)
