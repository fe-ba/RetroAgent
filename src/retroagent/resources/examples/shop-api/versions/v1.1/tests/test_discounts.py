import pytest

from shop.discounts import apply_coupon
from shop.errors import CouponNotAllowed, InvalidCoupon
from shop.pricing import totals


def test_req_004_coupon_reduces_subtotal_by_percentage(store, cart):
    cart.add_item(store.stock, "p-102", 1)
    apply_coupon(cart, "WELCOME10")
    result = totals(cart)
    assert str(result.subtotal) == "80.00"
    assert str(result.discount) == "8.00"


def test_req_004_unknown_coupon_is_rejected(store, cart):
    cart.add_item(store.stock, "p-102", 1)
    with pytest.raises(InvalidCoupon):
        apply_coupon(cart, "FREE100")
    assert str(totals(cart).discount) == "0.00"


def test_req_004_second_coupon_is_rejected(store, cart):
    cart.add_item(store.stock, "p-102", 1)
    apply_coupon(cart, "WELCOME10")
    with pytest.raises(CouponNotAllowed):
        apply_coupon(cart, "VIP5")
    assert str(totals(cart).discount) == "8.00"


def test_req_004_discount_applies_before_tax(store, cart):
    cart.add_item(store.stock, "p-102", 1)
    apply_coupon(cart, "WELCOME10")
    assert str(totals(cart).tax) == "13.68"


def test_req_004_two_coupons_are_combined(store, cart):
    cart.add_item(store.stock, "p-102", 1)
    apply_coupon(cart, "WELCOME10")
    apply_coupon(cart, "VIP5")
    assert str(totals(cart).discount) == "12.00"


def test_req_004_third_coupon_is_rejected(store, cart):
    cart.add_item(store.stock, "p-102", 1)
    apply_coupon(cart, "WELCOME10")
    apply_coupon(cart, "VIP5")
    with pytest.raises(CouponNotAllowed):
        apply_coupon(cart, "SPRING20")
    assert str(totals(cart).discount) == "12.00"
