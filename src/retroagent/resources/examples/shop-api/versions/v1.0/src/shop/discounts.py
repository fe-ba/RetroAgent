"""Discount coupons."""

from decimal import Decimal

from shop.cart import Cart
from shop.errors import CouponNotAllowed, InvalidCoupon
from shop.money import money

COUPONS = {
    "WELCOME10": 10,
    "SPRING20": 20,
    "VIP5": 5,
}


def apply_coupon(cart: Cart, code: str) -> None:
    if code not in COUPONS:
        raise InvalidCoupon(f"unknown coupon: {code}")
    if cart.coupon is not None:
        raise CouponNotAllowed("only one coupon applies per order")
    cart.coupon = code


def discount_amount(subtotal: Decimal, cart: Cart) -> Decimal:
    if cart.coupon is None:
        return money(0)
    return money(subtotal * COUPONS[cart.coupon] / 100)
