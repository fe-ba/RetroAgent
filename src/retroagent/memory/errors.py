"""Errors of the data layer."""


class InvariantViolation(Exception):
    """A write was refused by the data layer API. The message starts with the invariant, e.g. ``INV-13``.

    Refusals made by CHECK constraints and triggers are ``sqlite3.IntegrityError`` with the same prefix.
    """


class SchemaTooNew(Exception):
    """The database was created by a newer RetroAgent; the user must update RetroAgent."""
