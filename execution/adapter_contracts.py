"""Validação de capacidades de adapters antes de efeitos externos."""

from __future__ import annotations

import inspect
from typing import Any, Callable


def supports_client_order_id(method: Callable[..., Any]) -> bool:
    """Não considera `**kwargs` prova de idempotência; exige parâmetro explícito."""
    try:
        return "client_order_id" in inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False
