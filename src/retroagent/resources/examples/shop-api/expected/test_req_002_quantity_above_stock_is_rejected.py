"""TC-027: a quantity above the stock of a product is rejected (REQ-002)."""

import pytest

from shop.errors import InsufficientStock
from shop.store import Store


def test_req_002_quantity_above_stock_is_rejected():
    store = Store()
    cart = store.create_cart()
    cart.add_item(store.stock, "p-102", 3)
    with pytest.raises(InsufficientStock):
        cart.add_item(store.stock, "p-102", 3)
    assert cart.items == {"p-102": 3}
