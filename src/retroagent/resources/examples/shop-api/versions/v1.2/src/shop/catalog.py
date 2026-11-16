"""Product catalog and product search."""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from shop.errors import NotFound
from shop.money import money

CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache"


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    price: Decimal
    stock: int


PRODUCTS = [
    Product("p-100", "Wireless Mouse", money("25.00"), 50),
    Product("p-101", "USB-C Cable 1m", money("7.50"), 50),
    Product("p-102", "Mechanical Keyboard", money("80.00"), 5),
    Product("p-103", "HDMI Cable 2m", money("12.00"), 50),
    Product("p-104", "Laptop Stand", money("40.00"), 50),
    Product("p-105", "Webcam HD", money("55.00"), 50),
    Product("p-106", "Notebook A5", money("1.50"), 50),
]

_BY_ID = {product.id: product for product in PRODUCTS}


def list_products() -> list[Product]:
    return sorted(PRODUCTS, key=lambda product: product.name.lower())


def get_product(product_id: str) -> Product:
    try:
        return _BY_ID[product_id]
    except KeyError:
        raise NotFound(f"unknown product: {product_id}") from None


def search(term: str) -> list[Product]:
    """Products whose name contains term, ignoring case."""
    needle = term.lower()
    return [_BY_ID[product_id] for name, product_id in _search_index() if needle in name]


def _search_index() -> list[list[str]]:
    """Lowercase names with their product IDs. Built once and kept on disk."""
    path = CACHE_DIR / "search-index.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    entries = [[product.name.lower(), product.id] for product in PRODUCTS]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(entries)), encoding="utf-8")
    return entries
