"""HTTP API of the shop, on the standard library HTTP server."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from shop import catalog
from shop.discounts import apply_coupon
from shop.errors import NotFound, ShopError
from shop.money import as_text
from shop.orders import checkout
from shop.pricing import totals
from shop.store import Store


def product_view(product) -> dict:
    return {"id": product.id, "name": product.name, "price": as_text(product.price)}


def cart_view(cart) -> dict:
    return {"cart_id": cart.id, "items": cart.items, "coupon": cart.coupon, "totals": totals(cart).as_dict()}


class ShopHandler(BaseHTTPRequestHandler):
    store: Store

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def log_message(self, format, *args):
        pass

    def _dispatch(self, method: str) -> None:
        parts = [part for part in self.path.split("?")[0].split("/") if part]
        try:
            status, body = self._route(method, parts)
        except ShopError as error:
            status, body = error.status, {"error": str(error)}
        except (ValueError, KeyError, TypeError):
            status, body = 400, {"error": "invalid request"}
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def _route(self, method: str, parts: list[str]):
        store = self.store
        match (method, parts):
            case ("GET", ["health"]):
                return 200, {"status": "ok"}
            case ("GET", ["products"]):
                return 200, [product_view(product) for product in catalog.list_products()]
            case ("GET", ["products", product_id]):
                return 200, product_view(catalog.get_product(product_id))
            case ("POST", ["carts"]):
                return 201, cart_view(store.create_cart())
            case ("GET", ["carts", cart_id]):
                return 200, cart_view(store.get_cart(cart_id))
            case ("POST", ["carts", cart_id, "items"]):
                cart, data = store.get_cart(cart_id), self._json()
                cart.add_item(store.stock, data["product_id"], data["quantity"])
                return 201, cart_view(cart)
            case ("POST", ["carts", cart_id, "coupons"]):
                cart = store.get_cart(cart_id)
                apply_coupon(cart, self._json()["code"])
                return 200, cart_view(cart)
            case ("POST", ["carts", cart_id, "checkout"]):
                return 201, checkout(store, store.get_cart(cart_id)).as_dict()
        raise NotFound("no such resource")


def make_server(port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    handler = type("Handler", (ShopHandler,), {"store": Store()})
    return ThreadingHTTPServer((host, port), handler)
