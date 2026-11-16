"""Errors raised by the shop, with the HTTP status the API answers with."""


class ShopError(Exception):
    status = 400


class NotFound(ShopError):
    status = 404


class InvalidQuantity(ShopError):
    status = 400


class InsufficientStock(ShopError):
    status = 409


class InvalidCoupon(ShopError):
    status = 400


class CouponNotAllowed(ShopError):
    status = 409


class EmptyCart(ShopError):
    status = 400
