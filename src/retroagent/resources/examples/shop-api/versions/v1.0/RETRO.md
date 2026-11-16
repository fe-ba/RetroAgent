# shop-api

## Overview

Back end of a small online shop. Customers browse a product catalog, fill a cart, apply discount coupons and check out. Prices include shipping and value added tax.

## Modules

| Module | Responsibility |
|---|---|
| `src/shop/catalog.py` | Products, lookup and search. |
| `src/shop/cart.py` | Cart contents and stock check when adding. |
| `src/shop/discounts.py` | Coupons. |
| `src/shop/shipping.py` | Shipping cost. |
| `src/shop/tax.py` | Value added tax. |
| `src/shop/pricing.py` | Totals of a cart: subtotal, discount, tax, shipping, total. |
| `src/shop/orders.py` | Checkout. |
| `src/shop/store.py` | In-memory state. |
| `src/shop/api.py` | HTTP API. |

## Running

- No runtime dependencies. Tests need pytest (`requirements-dev.txt`).
- Start the API with `python serve.py --port <port>`. `GET /health` answers when it is ready.

## Test conventions

- pytest, in `tests/`. One file per area.
- Test functions are named `test_req_<NNN>_<description>`, with the number of the requirement they verify.
- Unit tests import `shop` directly and use the fixtures `store` and `cart` from `tests/conftest.py`.
- API tests use the fixture `base_url` and the helper `tests.client.call`. Amounts are JSON strings with two decimals.
- State is in memory and per process. API tests must create their own cart.

## Known issues

None recorded.
