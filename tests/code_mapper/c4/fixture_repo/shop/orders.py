"""Order orchestration with resolved and unresolved call targets."""

import os  # Intentionally unused: must not create a counted reference.
from typing import TYPE_CHECKING

from .payments import PaymentGateway, load_gateway
from .storage import Storage

if TYPE_CHECKING:
    from .storage import OrderRecord


def place_order(order_id: str, total: int) -> None:
    gateway = PaymentGateway()
    gateway.charge(total)  # Bound receiver with a known implementation.
    load_gateway().charge(total)  # No local receiver binding.
    storage = Storage()
    storage.save(order_id)


def describe_order(record: "OrderRecord") -> str:
    return record.order_id
