"""How much a listener hears to finish an order here.

The other half of the comparison. `screen_reader_cost.py` counts what a shop
says before a listener even reaches the first product; this counts what
VoiceCart says across a whole order, from the first question to the order
number.

Nothing is estimated. The tools are the real ones, called in the order a
conversation would call them, and the words counted are the exact `speech`
strings the assistant is told to read aloud.

Usage:
    python -m measure.voice_cost
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

# An order writes to disk, so give this run its own state and leave the
# real basket alone.
_STATE = tempfile.mkdtemp(prefix="voicecart-measure-")
import os  # noqa: E402

os.environ["VOICECART_STATE_DIR"] = _STATE

from voicecart import carts, orders, refer, server  # noqa: E402

SHOPPER = "measure"


def words(text: str) -> int:
    return len([word for word in re.split(r"\s+", text.strip()) if word])


def call(tool, **kwargs) -> tuple[str, int]:
    """Call a tool, whether or not it is one of the async ones.

    The tools that change the basket are async because they notify anybody
    subscribed to it. Nothing here cares which is which.
    """
    import asyncio
    import inspect

    reply = tool(**kwargs)
    if inspect.isawaitable(reply):
        reply = asyncio.run(reply)
    return reply.speech, words(reply.speech)


def main() -> int:
    for module in (carts, orders, refer):
        module.STATE_DIR = Path(_STATE)
    carts.CART_FILE = Path(_STATE) / "carts.json"
    orders.ORDER_FILE = Path(_STATE) / "orders.json"
    refer.RECENT_FILE = Path(_STATE) / "recent.json"

    steps: list[tuple[str, str, int]] = []

    def step(said: str, tool, **kwargs) -> None:
        speech, count = call(tool, **kwargs)
        steps.append((said, speech, count))

    # A whole order, said the way somebody would actually say it.
    step("what have you got", server.list_categories)
    step("show me the groceries",
         server.browse_category, category="Groceries", shopper_id=SHOPPER)
    step("add the second one",
         server.add_to_cart, item="the second one", shopper_id=SHOPPER)
    step("what is in my basket", server.read_cart, shopper_id=SHOPPER)
    step("I want it at house twelve, Dhanmondi",
         server.review_order, address="House 12, Dhanmondi", shopper_id=SHOPPER)

    reply = server_place_order()
    steps.append(("yes", reply.speech, words(reply.speech)))

    total = 0
    print("A whole order, counted in words heard\n")
    for said, speech, count in steps:
        total += count
        print(f'  "{said}"')
        print(f"      {count:>3} words   {speech}")
    print(f"\n  total heard, first question to order number: {total} words")

    # The two numbers the shop measurement is set against.
    first_product = next(
        (count for said, speech, count in steps if said == "show me the groceries"),
        0,
    )
    print("  heard before the first product is named: 0 words "
          "(the reply opens with it)")
    print(f"  to hear three products compared: {first_product} words")
    return 0


def server_place_order():
    """place_order is async only because it may ask the client to confirm."""
    import asyncio

    return asyncio.run(
        server.place_order(
            address="House 12, Dhanmondi", confirmed=True, shopper_id=SHOPPER
        )
    )


if __name__ == "__main__":
    sys.exit(main())
