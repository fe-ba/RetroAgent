# Requirements of shop-api

Amounts are expressed with two decimals.

## REQ-001: Product catalog

The shop lists its products sorted by name, and returns one product by its ID. An unknown ID is answered as not found. Search returns the products whose name contains the search term, ignoring case, sorted by name.

- Priority: medium
- Since: v1.0

## REQ-002: Adding products to the cart

A product is added to a cart with a quantity of 1 or more. The quantity of a product in a cart, counting what the cart already holds, cannot exceed its stock; a request above the stock is rejected and leaves the cart unchanged. An unknown product is answered as not found.

- Priority: high
- Since: v1.0

## REQ-003: Cart totals

The subtotal of a cart is the sum of price times quantity of its items. The total is the subtotal, minus the discount, plus tax and shipping. An empty cart has a total of zero.

- Priority: high
- Since: v1.0

## REQ-004: Discount coupons

A valid coupon reduces the subtotal by its percentage. Only one coupon applies per order: a second coupon is rejected. An unknown coupon is rejected and changes nothing.

- Priority: high
- Since: v1.0

## REQ-005: Shipping

Shipping is free when the subtotal after discounts is 100.00 or more. Otherwise shipping costs a flat 8.00. An empty cart has no shipping cost.

- Priority: medium
- Since: v1.0

## REQ-006: Checkout

Checking out a cart creates an order with the items and the totals of the cart, reduces the stock of each product by the quantity ordered, and empties the cart. An empty cart cannot be checked out.

- Priority: high
- Since: v1.0

## REQ-007: Tax

Value added tax is 19% of the subtotal after discounts. Shipping is not taxed. The tax amount is rounded half up to two decimals.

- Priority: medium
- Since: v1.0
