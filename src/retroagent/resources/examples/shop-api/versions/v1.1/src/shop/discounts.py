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

MAX_COUPONS = 2


def apply_coupon(cart: Cart, code: str) -> None:
    if code not in COUPONS:
        raise InvalidCoupon(f"unknown coupon: {code}")
    if code in cart.coupons:
        raise CouponNotAllowed(f"coupon already applied: {code}")
    if len(cart.coupons) >= MAX_COUPONS:
        raise CouponNotAllowed(f"at most {MAX_COUPONS} coupons apply per order")
    cart.coupons.append(code)


def discount_percentage(cart: Cart) -> int:
    return sum(COUPONS[code] for code in cart.coupons)


def discount_amount(subtotal: Decimal, cart: Cart) -> Decimal:
    return money(subtotal * discount_percentage(cart) / 100)
