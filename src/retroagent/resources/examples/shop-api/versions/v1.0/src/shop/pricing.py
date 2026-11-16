"""Totals of a cart."""

from dataclasses import dataclass
from decimal import Decimal

from shop.cart import Cart
from shop.catalog import get_product
from shop.discounts import discount_amount
from shop.money import as_text, money
from shop.shipping import shipping_cost
from shop.tax import tax_amount


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    discount: Decimal
    tax: Decimal
    shipping: Decimal
    total: Decimal

    def as_dict(self) -> dict[str, str]:
        return {
            "subtotal": as_text(self.subtotal),
            "discount": as_text(self.discount),
            "tax": as_text(self.tax),
            "shipping": as_text(self.shipping),
            "total": as_text(self.total),
        }


def totals(cart: Cart) -> Totals:
    subtotal = money(sum(get_product(pid).price * qty for pid, qty in cart.items.items()))
    discount = discount_amount(subtotal, cart)
    discounted = subtotal - discount
    tax = tax_amount(discounted)
    shipping = shipping_cost(discounted)
    return Totals(subtotal, discount, tax, shipping, discounted + tax + shipping)
