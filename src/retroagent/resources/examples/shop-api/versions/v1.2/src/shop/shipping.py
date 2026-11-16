"""Shipping cost."""

from decimal import Decimal

from shop.money import money

FREE_SHIPPING_FROM = money("100.00")
FLAT_RATE = money("8.00")


def shipping_cost(amount: Decimal) -> Decimal:
    """Shipping for an order of this amount. An empty order ships nothing."""
    if amount == 0 or amount >= FREE_SHIPPING_FROM:
        return money(0)
    return FLAT_RATE
