import pytest

from shop import catalog
from shop.errors import NotFound


def test_req_001_products_are_listed_sorted_by_name():
    names = [product.name for product in catalog.list_products()]
    assert names == sorted(names, key=str.lower)
    assert len(names) == 7


def test_req_001_product_has_name_and_price():
    product = catalog.get_product("p-100")
    assert product.name == "Wireless Mouse"
    assert str(product.price) == "25.00"


def test_req_001_unknown_product_is_not_found():
    with pytest.raises(NotFound):
        catalog.get_product("p-999")


def test_req_001_search_results_are_sorted_by_name():
    names = [product.name for product in catalog.search("CABLE")]
    assert names == ["HDMI Cable 2m", "USB-C Cable 1m"]
