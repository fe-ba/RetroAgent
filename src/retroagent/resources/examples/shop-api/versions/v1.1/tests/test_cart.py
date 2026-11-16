from shop.pricing import totals


def test_req_003_subtotal_is_sum_of_price_times_quantity(store, cart):
    cart.add_item(store.stock, "p-100", 2)
    cart.add_item(store.stock, "p-103", 1)
    assert str(totals(cart).subtotal) == "62.00"


def test_req_003_total_adds_tax_and_shipping(store, cart):
    cart.add_item(store.stock, "p-100", 2)
    cart.add_item(store.stock, "p-103", 1)
    result = totals(cart)
    assert str(result.tax) == "11.78"
    assert str(result.shipping) == "8.00"
    assert str(result.total) == "81.78"


def test_req_003_empty_cart_total_is_zero(cart):
    result = totals(cart)
    assert str(result.subtotal) == "0.00"
    assert str(result.total) == "0.00"


def test_req_003_removing_item_updates_subtotal(store, cart):
    cart.add_item(store.stock, "p-100", 1)
    cart.add_item(store.stock, "p-104", 1)
    cart.remove_item("p-104")
    assert str(totals(cart).subtotal) == "25.00"
