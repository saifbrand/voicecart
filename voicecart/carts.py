"""Carts that outlive the conversation.

A sighted shopper leaves a browser tab open. A voice shopper has no tab: when
the session ends, whatever they were doing is gone unless somebody stored it.
So the cart is keyed to the shopper and written to disk, and picking up
tomorrow means saying "what is in my basket".
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from voicecart import catalogue

STATE_DIR = Path(
    os.environ.get("VOICECART_STATE_DIR")
    or Path(__file__).resolve().parent.parent / "data"
)
CART_FILE = STATE_DIR / "carts.json"
MAX_QUANTITY = 20


@dataclass
class Line:
    sku: str
    quantity: int

    @property
    def product(self) -> catalogue.Product | None:
        return catalogue.get(self.sku)

    @property
    def subtotal(self) -> float:
        product = self.product
        return product.price * self.quantity if product else 0.0


@dataclass
class Cart:
    shopper_id: str
    lines: list[Line] = field(default_factory=list)
    last_order_skus: list[str] = field(default_factory=list)
    """What they bought last time, so "the usual" means something."""

    @property
    def total(self) -> float:
        return sum(line.subtotal for line in self.lines)

    @property
    def is_empty(self) -> bool:
        return not self.lines

    def find(self, sku: str) -> Line | None:
        return next((line for line in self.lines if line.sku == sku), None)

    def add(self, sku: str, quantity: int) -> int:
        """Add and return the resulting quantity, clamped to what is in stock."""
        product = catalogue.get(sku)
        if product is None:
            raise KeyError(sku)

        line = self.find(sku)
        wanted = (line.quantity if line else 0) + quantity
        allowed = max(0, min(wanted, product.in_stock, MAX_QUANTITY))

        if allowed == 0:
            if line:
                self.lines.remove(line)
            return 0
        if line:
            line.quantity = allowed
        else:
            self.lines.append(Line(sku=sku, quantity=allowed))
        return allowed

    def remove(self, sku: str) -> bool:
        line = self.find(sku)
        if line is None:
            return False
        self.lines.remove(line)
        return True

    def clear(self) -> None:
        self.lines = []


def _read_all() -> dict[str, Any]:
    if not CART_FILE.exists():
        return {}
    return json.loads(CART_FILE.read_text(encoding="utf-8"))


def _write_all(data: dict[str, Any]) -> None:
    CART_FILE.parent.mkdir(parents=True, exist_ok=True)
    CART_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load(shopper_id: str) -> Cart:
    row = _read_all().get(shopper_id)
    if not row:
        return Cart(shopper_id=shopper_id)
    return Cart(
        shopper_id=shopper_id,
        lines=[Line(**line) for line in row.get("lines", [])],
        last_order_skus=row.get("last_order_skus", []),
    )


def save(cart: Cart) -> None:
    data = _read_all()
    data[cart.shopper_id] = {
        "lines": [{"sku": line.sku, "quantity": line.quantity} for line in cart.lines],
        "last_order_skus": cart.last_order_skus,
    }
    _write_all(data)
