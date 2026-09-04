"""The storefront. Shaped like a WooCommerce product payload.

`STORE_SOURCE=demo` reads the bundled JSON. Pointing it at a live shop means
replacing `_load` with one REST call; nothing above this module knows the
difference.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CATALOGUE_FILE = Path(__file__).resolve().parent.parent / "data" / "catalogue.json"


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    category: str
    price: float
    unit: str
    in_stock: int
    blurb: str
    allergens: list[str]
    heavy: bool

    @property
    def available(self) -> bool:
        return self.in_stock > 0


@lru_cache(maxsize=1)
def _load() -> tuple[Product, ...]:
    rows = json.loads(CATALOGUE_FILE.read_text(encoding="utf-8"))
    return tuple(Product(**row) for row in rows)


def all_products() -> list[Product]:
    return list(_load())


def categories() -> list[str]:
    seen: list[str] = []
    for product in _load():
        if product.category not in seen:
            seen.append(product.category)
    return seen


def get(sku: str) -> Product | None:
    wanted = sku.strip().upper()
    for product in _load():
        if product.sku == wanted:
            return product
    return None


def in_category(category: str) -> list[Product]:
    wanted = category.strip().casefold()
    return [p for p in _load() if p.category.casefold() == wanted]


def _words(text: str) -> set[str]:
    """Whole words, singular. Speech gives you words, not substrings."""
    return {_singular(w) for w in re.findall(r"[a-z0-9]+", text.casefold())}


def _singular(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def search(query: str) -> list[Product]:
    """Match whole spoken words, not substrings.

    Somebody says "honey", never "hon", and a substring match on "hon" would
    hand them honey as though they had asked for it. Ranking puts a name
    match above a description match, because the name is what they said.
    """
    wanted = {w for w in _words(query) if len(w) > 1}
    if not wanted:
        return []

    scored: list[tuple[int, Product]] = []
    for product in _load():
        name_words = _words(product.name)
        other_words = _words(f"{product.category} {product.blurb}")
        score = 0
        for word in wanted:
            if word in name_words:
                score += 3
            elif word in other_words:
                score += 1
        if score:
            # In stock first: reading out something they cannot buy wastes
            # the one channel a voice shopper has.
            scored.append((score + (2 if product.available else 0), product))

    scored.sort(key=lambda pair: (pair[0], -pair[1].price), reverse=True)
    return [product for _, product in scored]
