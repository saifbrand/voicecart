"""Placing and tracking orders.

Cash on delivery, because that is how this shop's customers pay: nothing is
charged now, the courier collects at the door. That matters for a voice
flow, since it means an order can be placed without ever asking anybody to
say a card number out loud.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from voicecart import catalogue
from voicecart.carts import STATE_DIR, Cart

ORDER_FILE = STATE_DIR / "orders.json"

STAGES = [
    ("placed", "We have your order."),
    ("packed", "It is packed and waiting for the courier."),
    ("with courier", "The courier has it."),
    ("out for delivery", "It is out for delivery today."),
    ("delivered", "It was delivered."),
]


@dataclass
class Order:
    id: str
    shopper_id: str
    lines: list[dict[str, Any]]
    total: float
    address: str
    placed_at: str
    stage: str = "placed"

    @property
    def spoken_stage(self) -> str:
        for name, sentence in STAGES:
            if name == self.stage:
                return sentence
        return "We are checking on it."


def _read_all() -> list[dict[str, Any]]:
    if not ORDER_FILE.exists():
        return []
    return json.loads(ORDER_FILE.read_text(encoding="utf-8"))


def _write_all(rows: list[dict[str, Any]]) -> None:
    ORDER_FILE.parent.mkdir(parents=True, exist_ok=True)
    ORDER_FILE.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def _new_id() -> str:
    """Short enough to say out loud and hear back correctly.

    Digits only, in two groups. Letters get confused over a phone speaker,
    and a shopper who cannot read the screen has to repeat this number to a
    courier.
    """
    return f"{random.randint(10, 99)}-{random.randint(1000, 9999)}"


def place(cart: Cart, address: str) -> Order:
    if cart.is_empty:
        raise ValueError("Cannot place an empty order.")

    order = Order(
        id=_new_id(),
        shopper_id=cart.shopper_id,
        lines=[{"sku": line.sku,
                "name": line.product.name if line.product else line.sku,
                "quantity": line.quantity,
                "price": line.product.price if line.product else 0.0}
               for line in cart.lines],
        total=cart.total,
        address=address,
        placed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    rows = _read_all()
    rows.append(asdict(order))
    _write_all(rows)
    return order


def get(order_id: str) -> Order | None:
    wanted = order_id.replace(" ", "").strip()
    for row in _read_all():
        if row["id"].replace("-", "") == wanted.replace("-", ""):
            return Order(**row)
    return None


def latest_for(shopper_id: str) -> Order | None:
    mine = [row for row in _read_all() if row["shopper_id"] == shopper_id]
    return Order(**mine[-1]) if mine else None


def expected_delivery(order: Order) -> str:
    """A spoken window, not a timestamp."""
    placed = datetime.fromisoformat(order.placed_at)
    window = placed + timedelta(days=2)
    return window.strftime("%A")


def reorderable(shopper_id: str) -> list[catalogue.Product]:
    """What this shopper bought last time and can buy again today."""
    last = latest_for(shopper_id)
    if last is None:
        return []
    products = [catalogue.get(line["sku"]) for line in last.lines]
    return [p for p in products if p is not None and p.available]
