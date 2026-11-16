"""In-memory state of the shop: stock, carts and orders."""

from shop.cart import Cart
from shop.catalog import PRODUCTS
from shop.errors import NotFound


class Store:
    def __init__(self):
        self.stock = {product.id: product.stock for product in PRODUCTS}
        self.carts: dict[str, Cart] = {}
        self.orders: list = []
        self._next_cart = 1
        self._next_order = 1

    def create_cart(self) -> Cart:
        cart = Cart(f"c-{self._next_cart}")
        self._next_cart += 1
        self.carts[cart.id] = cart
        return cart

    def get_cart(self, cart_id: str) -> Cart:
        try:
            return self.carts[cart_id]
        except KeyError:
            raise NotFound(f"unknown cart: {cart_id}") from None

    def next_order_id(self) -> str:
        order_id = f"o-{self._next_order}"
        self._next_order += 1
        return order_id
