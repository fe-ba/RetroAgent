"""Shopping cart: products and quantities, and the coupon applied to it."""

from shop.catalog import get_product
from shop.errors import InsufficientStock, InvalidQuantity, NotFound


class Cart:
    def __init__(self, cart_id: str):
        self.id = cart_id
        self.items: dict[str, int] = {}
        self.coupon: str | None = None

    def add_item(self, stock: dict[str, int], product_id: str, quantity: int) -> None:
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise InvalidQuantity("quantity must be a whole number, 1 or more")
        get_product(product_id)
        wanted = self.items.get(product_id, 0) + quantity
        if wanted > stock[product_id]:
            raise InsufficientStock(f"only {stock[product_id]} units of {product_id} in stock")
        self.items[product_id] = wanted

    def remove_item(self, product_id: str) -> None:
        if product_id not in self.items:
            raise NotFound(f"{product_id} is not in the cart")
        del self.items[product_id]

    def is_empty(self) -> bool:
        return not self.items

    def clear(self) -> None:
        self.items.clear()
        self.coupon = None
