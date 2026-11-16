import pytest

from shop.errors import EmptyCart
from shop.orders import checkout


def test_req_006_checkout_decrements_stock_and_empties_cart(store, cart):
    cart.add_item(store.stock, "p-102", 2)
    order = checkout(store, cart)
    assert order.items == {"p-102": 2}
    assert store.stock["p-102"] == 3
    assert cart.is_empty()


def test_req_006_empty_cart_cannot_be_checked_out(store, cart):
    with pytest.raises(EmptyCart):
        checkout(store, cart)
    assert store.stock["p-102"] == 5
