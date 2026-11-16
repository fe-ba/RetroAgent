from shop.pricing import totals


def test_req_007_tax_is_19_percent_of_discounted_subtotal(store, cart):
    cart.add_item(store.stock, "p-104", 1)
    assert str(totals(cart).tax) == "7.60"


def test_req_007_tax_rounds_half_up(store, cart):
    cart.add_item(store.stock, "p-106", 1)
    result = totals(cart)
    assert str(result.subtotal) == "1.50"
    assert str(result.tax) == "0.29"
