from tests.client import call


def test_req_001_api_returns_product_by_id(base_url):
    status, body = call("GET", f"{base_url}/products/p-103")
    assert status == 200
    assert body == {"id": "p-103", "name": "HDMI Cable 2m", "price": "12.00"}


def test_req_003_api_cart_shows_totals(base_url):
    _, cart = call("POST", f"{base_url}/carts")
    status, body = call("POST", f"{base_url}/carts/{cart['cart_id']}/items", {"product_id": "p-100", "quantity": 2})
    assert status == 201
    assert body["totals"] == {
        "subtotal": "50.00",
        "discount": "0.00",
        "tax": "9.50",
        "shipping": "8.00",
        "total": "67.50",
    }


def test_req_006_api_checkout_creates_order(base_url):
    _, cart = call("POST", f"{base_url}/carts")
    call("POST", f"{base_url}/carts/{cart['cart_id']}/items", {"product_id": "p-100", "quantity": 1})
    status, order = call("POST", f"{base_url}/carts/{cart['cart_id']}/checkout")
    assert status == 201
    assert order["order_id"].startswith("o-")
    assert order["totals"]["total"] == "37.75"
