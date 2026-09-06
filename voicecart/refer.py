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
    """Record what was just read out, so it can be referred back to.

    A new list wipes the rejections: "not that one" was about the old list,
    and holding it against a fresh one would silently hide a product.
    """
    _write(shopper_id, {"shown": skus, "rejected": [], "resolved": ""})


def recent(shopper_id: str) -> list[str]:
    return _row(shopper_id).get("shown", [])


def resolved(shopper_id: str) -> str:
    """What the last phrase was taken to mean."""
    return _row(shopper_id).get("resolved", "")


def note_resolved(shopper_id: str, sku: str) -> None:
    row = _row(shopper_id)
    row["resolved"] = sku
    _write(shopper_id, row)


def rejected(shopper_id: str) -> list[str]:
    return _row(shopper_id).get("rejected", [])


def reject(shopper_id: str, sku: str) -> None:
    """Take one product out of the running.

    "No, not that one" is not only an undo. It is also the shopper narrowing
    what they meant, and the next attempt at the same words should not land
    on the thing they just refused.
    """
    row = _row(shopper_id)
    marked = row.get("rejected", [])
    if sku and sku not in marked:
        marked.append(sku)
    row["rejected"] = marked
    _write(shopper_id, row)


def _row(shopper_id: str) -> dict:
    row = _read().get(shopper_id)
    if row is None:
        return {}
    # Baskets written before corrections existed hold a bare list of SKUs.
    if isinstance(row, list):
        return {"shown": row, "rejected": [], "resolved": ""}
    return dict(row)


def _write(shopper_id: str, row: dict) -> None:
    RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _read()
    data[shopper_id] = row
    RECENT_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _read() -> dict:
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
    refused = rejected(shopper_id)
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
        standing = [sku for sku in heard if sku not in refused]
        if len(standing) == 1:
            return Resolution(standing[0])
        if not heard:
            return Resolution(None, "I have not read anything out yet.")
        names = tuple(p.name for p in _products(standing or heard)[:3])
        return Resolution(
            None,
            "Do you mean " + " or ".join(names) + "?",
            names,
        )

    # A name. Search what was just read out before searching the whole shop.
    for pool in (_products(heard), catalogue.all_products()):
        matches = _without_refused(_by_name(words, pool), refused)
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


def _without_refused(
    matches: list[catalogue.Product], refused: list[str]
) -> list[catalogue.Product]:
    """Drop what the shopper has already said no to, unless that leaves nothing.

    If every match was refused, the phrase is handed back as it was: better
    to offer the same thing again and be told no than to answer "I could not
    find that" about something the shop plainly has.
    """
    standing = [product for product in matches if product.sku not in refused]
    return standing or matches


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
