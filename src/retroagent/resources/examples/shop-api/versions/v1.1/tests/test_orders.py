import pytest

from shop.errors import EmptyCart
from shop.orders import checkout, list_orders


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


def test_req_008_orders_are_listed_newest_first(store):
    for product_id in ("p-100", "p-104"):
        cart = store.create_cart()
        cart.add_item(store.stock, product_id, 1)
        checkout(store, cart)
    assert [order.id for order in list_orders(store)] == ["o-2", "o-1"]
