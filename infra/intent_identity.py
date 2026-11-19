"""Intent replay integrity; this is not financial-ledger authority."""
from decimal import Decimal, InvalidOperation
from typing import Any


class IntentIdempotencyConflict(RuntimeError):
    pass


def _number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("invalid_intent_identity")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid_intent_identity") from None
    if not number.is_finite():
        raise ValueError("invalid_intent_identity")
    return number


def intent_identity(account_id: str, order: dict) -> tuple:
    quantity = _number(order["quantity"])
    price = None if order.get("price") is None else _number(order["price"])
    if quantity <= 0 or (price is not None and price <= 0):
        raise ValueError("invalid_intent_identity")
    return (account_id, str(order["symbol"]).strip().upper(), str(order["action"]).strip().lower(),
            str(order.get("order_type", "market")).strip().lower(), quantity, price)


def assert_same_intent(existing: dict, account_id: str, order: dict) -> None:
    if intent_identity(existing.get("account_id"), existing) != intent_identity(account_id, order):
        raise IntentIdempotencyConflict("client_order_id já reservado para conta/parâmetros diferentes")
