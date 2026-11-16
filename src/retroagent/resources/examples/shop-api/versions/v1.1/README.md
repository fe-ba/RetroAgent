# shop-api

A small shop back end: product catalog, cart, discount coupons, shipping, tax, checkout and order history. It has no runtime dependencies; the HTTP API runs on the Python standard library.

## Run

```
python serve.py --port 8000
```

## Test

```
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

On Windows, use `.venv\Scripts\python` instead of `.venv/bin/python`.

Requirements are documented in `docs/requirements.md`. Test names carry the ID of the requirement they verify.
