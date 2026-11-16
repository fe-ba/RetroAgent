"""Checkout and order history."""

from dataclasses import dataclass

from shop.cart import Cart
from shop.errors import EmptyCart, InsufficientStock, NotFound
from shop.pricing import Totals, totals
from shop.store import Store


@dataclass(frozen=True)
class Order:
    id: str
    items: dict[str, int]
    totals: Totals

    def as_dict(self) -> dict:
        return {"order_id": self.id, "items": self.items, "totals": self.totals.as_dict()}


def checkout(store: Store, cart: Cart) -> Order:
    if cart.is_empty():
        raise EmptyCart("an empty cart cannot be checked out")
    for product_id, quantity in cart.items.items():
        if quantity > store.stock[product_id]:
            raise InsufficientStock(f"only {store.stock[product_id]} units of {product_id} in stock")
    order = Order(store.next_order_id(), dict(cart.items), totals(cart))
    for product_id, quantity in cart.items.items():
        store.stock[product_id] -= quantity
    store.orders.append(order)
    cart.clear()
    return order


def list_orders(store: Store) -> list[Order]:
    """Orders of the shop, newest first."""
    return list(reversed(store.orders))


def get_order(store: Store, order_id: str) -> Order:
    for order in store.orders:
        if order.id == order_id:
            return order
    raise NotFound(f"unknown order: {order_id}")
