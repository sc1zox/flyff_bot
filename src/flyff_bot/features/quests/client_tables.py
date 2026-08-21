"""Readers for the client's tab-separated property tables and localized text catalogs.

Quest scripts reference monsters and items by symbol (``MI_AIBATT1``, ``II_WEA_SWO_LONG``)
and their prose by string identifier (``IDS_PROPQUEST_INC_000469``). The property tables
map a symbol to its string identifier, and the language catalogs map that identifier to the
text an operator actually reads.
"""

from __future__ import annotations

# The client writes these files either as UTF-16 with a byte-order mark or as ANSI.
UTF16_BYTE_ORDER_MARKS = (b"\xff\xfe", b"\xfe\xff")
CLIENT_TEXT_FALLBACK_ENCODING = "cp1252"

# Symbol prefixes the property tables use for their two subject kinds.
MONSTER_SYMBOL_PREFIX = "MI_"
ITEM_SYMBOL_PREFIX = "II_"
# Every localized string the client resolves is referenced through this prefix.
STRING_REFERENCE_PREFIX = "IDS_"
# A property table writes this in a column it has no value for.
TABLE_EMPTY_FIELD = "="
# A catalog line is `<identifier><tab><text>`; later columns are per-language leftovers.
CATALOG_TEXT_COLUMN = 1


def decode_client_text(payload: bytes) -> str:
    """Return one client text file's contents, whichever of its encodings it uses."""

    if payload[:2] in UTF16_BYTE_ORDER_MARKS:
        return payload.decode("utf-16", errors="replace")
    return payload.decode(CLIENT_TEXT_FALLBACK_ENCODING, errors="replace")


def parse_text_catalog(text: str) -> dict[str, str]:
    """Return the ``IDS_...`` to localized-text mapping one language catalog declares."""

    catalog: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith(STRING_REFERENCE_PREFIX):
            continue
        columns = line.split("\t")
        if len(columns) <= CATALOG_TEXT_COLUMN:
            continue
        identifier = columns[0].strip()
        value = columns[CATALOG_TEXT_COLUMN].strip()
        if identifier and identifier not in catalog:
            catalog[identifier] = value
    return catalog


def parse_symbol_names(text: str, symbol_prefix: str, catalog: dict[str, str]) -> dict[str, str]:
    """Return the symbol-to-display-name mapping one property table declares.

    The tables differ in how many leading columns they carry, so the symbol column is found
    by its prefix and the string reference is read from the column right after it. A symbol
    whose string is missing from the catalog is skipped rather than labelled with its own
    identifier, which lets a caller fall back to the raw symbol deliberately.
    """

    names: dict[str, str] = {}
    for line in text.splitlines():
        columns = [column.strip() for column in line.split("\t")]
        for index, column in enumerate(columns[:-1]):
            if not column.startswith(symbol_prefix):
                continue
            reference = columns[index + 1]
            if not reference.startswith(STRING_REFERENCE_PREFIX):
                break
            value = catalog.get(reference, "")
            if value and value != TABLE_EMPTY_FIELD and column not in names:
                names[column] = value
            break
    return names
