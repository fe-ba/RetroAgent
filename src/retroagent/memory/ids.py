"""Identifiers of the glossary, assigned in sequence by the data layer (INV-07)."""

import sqlite3

# prefix -> (table, digits). REQ is not here: requirement identifiers are taken from the requirement documents.
_SEQUENCES = {
    "TC": ("test_case", 3),
    "RUN": ("run", 4),
    "DEF": ("defect", 3),
    "RSK": ("risk", 3),
    "RPT": ("report", 4),
}


def next_id(conn: sqlite3.Connection, prefix: str) -> str:
    """Next identifier of a sequence, e.g. ``TC-004``. Call it inside the transaction that inserts the record.

    Records are never deleted (INV-11), so the highest stored number is always the last one assigned.
    """
    table, digits = _SEQUENCES[prefix]
    row = conn.execute(f"SELECT MAX(CAST(SUBSTR(id, ?) AS INTEGER)) FROM {table}", (len(prefix) + 2,)).fetchone()
    return f"{prefix}-{(row[0] or 0) + 1:0{digits}d}"
