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

# How far back a correction can reach. Nobody says "undo" eight times, and a
# basket that remembers forever is a file that grows forever.
MAX_HISTORY = 8


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
    history: list[list[dict[str, Any]]] = field(default_factory=list)
    """The basket before each of the last few changes, so a step can be taken back.

    Snapshots rather than reversible operations, because an add is not
    reversible on its own: it may have been clamped to what was in stock, or
    merged into a line that was already there. Putting the whole basket back
    the way it was is the only undo that is always right.
    """

    @property
    def total(self) -> float:
        return sum(line.subtotal for line in self.lines)

    @property
    def is_empty(self) -> bool:
        return not self.lines

    @property
    def can_undo(self) -> bool:
        return bool(self.history)

    def find(self, sku: str) -> Line | None:
        return next((line for line in self.lines if line.sku == sku), None)

    def _remember(self) -> None:
        """Keep the basket as it is now, before it is about to change."""
        self.history.append(
            [{"sku": line.sku, "quantity": line.quantity} for line in self.lines]
        )
        del self.history[:-MAX_HISTORY]

    def undo(self) -> bool:
        """Put the basket back the way it was before the last change."""
        if not self.history:
            return False
        self.lines = [Line(**line) for line in self.history.pop()]
        return True

    def add(self, sku: str, quantity: int) -> int:
        """Add and return the resulting quantity, clamped to what is in stock."""
        product = catalogue.get(sku)
        if product is None:
            raise KeyError(sku)

        self._remember()
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
        self._remember()
        self.lines.remove(line)
        return True

    def empty(self) -> None:
        """Start again. Still a change, so it can still be taken back."""
        self._remember()
        self.lines = []

    def clear(self) -> None:
        """Wipe the basket after an order.

        Unlike `empty`, this cannot be undone: the order is placed, and
        handing somebody back a basket they have already bought would be a
        lie about what they owe.
        """
        self.lines = []
        self.history = []


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
        history=row.get("history", []),
    )


def save(cart: Cart) -> None:
    data = _read_all()
    data[cart.shopper_id] = {
        "lines": [{"sku": line.sku, "quantity": line.quantity} for line in cart.lines],
        "last_order_skus": cart.last_order_skus,
        # A correction can arrive tomorrow as easily as a second later, so
        # what can be taken back outlives the conversation too.
        "history": cart.history,
    }
    _write_all(data)
