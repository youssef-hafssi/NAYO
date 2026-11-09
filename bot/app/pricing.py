"""Prices are computed here and only here — never by the AI, never trusted from the browser."""

PRODUCT_NAME = "NAYO® Déodorant"
UNIT_PRICE = 189
SHIPPING = 20  # flat, whatever the quantity
CURRENCY = "MAD"
MAX_QTY = 10


def order_total(quantity: int) -> int:
    if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_QTY:
        raise ValueError(f"quantity must be an integer between 1 and {MAX_QTY}")
    return quantity * UNIT_PRICE + SHIPPING
