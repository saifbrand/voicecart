"""Working out which product somebody meant.

Nobody says "add HON dash zero zero three". They say "the second one", or
"the honey", or just "that one", and they say it about whatever was read out
a moment ago. On a screen you point; in a conversation you refer back.

So the server remembers the last thing it read to each shopper, and resolves
against it. This is the piece that makes the shop feel like a conversation
rather than a form being filled in by voice.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from voicecart import catalogue

STATE_DIR = Path(
    os.environ.get("VOICECART_STATE_DIR")
    or Path(__file__).resolve().parent.parent / "data"
)
RECENT_FILE = STATE_DIR / "recent.json"

ORDINALS = {
    "first": 0, "1st": 0, "one": 0, "1": 0,
    "second": 1, "2nd": 1, "two": 1, "2": 1,
    "third": 2, "3rd": 2, "three": 2, "3": 2,
    "fourth": 3, "4th": 3, "four": 3, "4": 3,
    "fifth": 4, "5th": 4, "five": 4, "5": 4,
    "last": -1, "final": -1,
}

# Words that carry no product meaning, so "the last one" reduces to "last".
FILLER = {"the", "that", "this", "one", "ones", "it", "item", "please", "a", "an"}


@dataclass(frozen=True)
class Resolution:
    """What the shopper meant, or why it could not be worked out."""

    sku: str | None
    reason: str = ""
    candidates: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return self.sku is not None


def remember(shopper_id: str, skus: list[str]) -> None:
    """Record what was just read out, so it can be referred back to."""
    RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _read()
    data[shopper_id] = skus
    RECENT_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def recent(shopper_id: str) -> list[str]:
    return _read().get(shopper_id, [])


def _read() -> dict[str, list[str]]:
    if not RECENT_FILE.exists():
        return {}
    return json.loads(RECENT_FILE.read_text(encoding="utf-8"))


def resolve(phrase: str, shopper_id: str) -> Resolution:
    """Turn what somebody said into one product, or explain the failure.

    Tried in the order a listener would expect:

    1. An exact SKU, because an assistant that already knows one should be
       able to say it.
    2. A position in what was just read out. "The second one" only means
       anything against a list, so this is checked before names.
    3. A name, against the recent list first and the whole shop second. A
       shopper saying "the honey" right after hearing three groceries means
       the honey they just heard, not a different honey elsewhere.

    An ambiguous phrase is never guessed at. Picking the wrong item for
    somebody who cannot see the basket is worse than asking again.
    """
    said = phrase.strip().casefold()
    if not said:
        return Resolution(None, "I did not catch that.")

    direct = catalogue.get(said.upper())
    if direct is not None:
        return Resolution(direct.sku)

    heard = recent(shopper_id)
    words = [w for w in re.findall(r"[a-z0-9]+", said) if w not in FILLER]

    # A position, but only when it is the whole of what they said. "second"
    # resolves; "second bedsheet" is a name, and should be treated as one.
    if len(words) == 1 and words[0] in ORDINALS:
        if not heard:
            return Resolution(None, "I have not read anything out yet.")
        index = ORDINALS[words[0]]
        try:
            return Resolution(heard[index])
        except IndexError:
            count = len(heard)
            noun = "was one item" if count == 1 else f"were {count} items"
            return Resolution(None, f"There {noun} in that list.")

    # Pure pointing: "that one", "it", "this". It means whatever was just
    # read out, but only when one thing was. After a list of three, "that
    # one" is genuinely ambiguous and guessing would be worse than asking.
    if not words:
        if len(heard) == 1:
            return Resolution(heard[0])
        if not heard:
            return Resolution(None, "I have not read anything out yet.")
        names = tuple(p.name for p in _products(heard)[:3])
        return Resolution(
            None,
            "Do you mean " + " or ".join(names) + "?",
            names,
        )

    # A name. Search what was just read out before searching the whole shop.
    for pool in (_products(heard), catalogue.all_products()):
        matches = _by_name(words, pool)
        if len(matches) == 1:
            return Resolution(matches[0].sku)
        if len(matches) > 1:
            names = tuple(p.name for p in matches[:3])
            return Resolution(
                None,
                "I have " + " or ".join(names) + ". Which one?",
                names,
            )

    return Resolution(None, f"I could not find {phrase}.")


def _products(skus: list[str]) -> list[catalogue.Product]:
    found = [catalogue.get(sku) for sku in skus]
    return [p for p in found if p is not None]


def _by_name(words: list[str], pool: list[catalogue.Product]) -> list[catalogue.Product]:
    """Products whose name contains every word the shopper used."""
    hits = []
    for product in pool:
        name = catalogue.words_of(product.name)
        if all(catalogue.singular(word) in name for word in words):
            hits.append(product)
    return hits
