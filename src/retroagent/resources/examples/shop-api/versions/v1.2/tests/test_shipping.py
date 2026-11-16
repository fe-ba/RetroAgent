from shop.discounts import apply_coupon
from shop.pricing import totals


def test_req_005_flat_rate_below_threshold(store, cart):
    cart.add_item(store.stock, "p-100", 1)
    assert str(totals(cart).shipping) == "8.00"


def test_req_005_free_shipping_at_threshold(store, cart):
    cart.add_item(store.stock, "p-100", 4)
    result = totals(cart)
    assert str(result.subtotal) == "100.00"
    assert str(result.shipping) == "0.00"


def test_req_005_shipping_charged_when_discount_drops_below_threshold(store, cart):
    cart.add_item(store.stock, "p-102", 1)
    cart.add_item(store.stock, "p-104", 1)
    apply_coupon(cart, "SPRING20")
    result = totals(cart)
    assert str(result.subtotal) == "120.00"
    assert str(result.discount) == "24.00"
    assert str(result.shipping) == "8.00"
