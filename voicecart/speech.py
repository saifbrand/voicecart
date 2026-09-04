"""Turn products into something worth hearing, and into cards worth showing.

Every tool here returns both. The spoken line is written to be listened to
once, without rewinding: short, no markup, the fact you need first. The card
is what Alexa+ renders on a screen when there is one, and it carries the
detail that would be tedious to hear.

Two rules the rest of the codebase leans on:

* Never read a long list. Three at a time, then offer the rest. A sighted
  shopper skims twenty results in two seconds; a listener cannot skip, so a
  twenty-item read-out is not thorough, it is a wall.
* Say the disqualifying fact first. "Out of stock" belongs before the price,
  not after it, or the listener spends the sentence deciding to buy
  something they cannot have.
"""
from __future__ import annotations

from typing import Any

from voicecart.carts import Cart
from voicecart.catalogue import Product

PAGE = 3
CURRENCY = "taka"


def money(amount: float) -> str:
    """Whole taka, spoken. No decimals: nobody says "three twenty point zero"."""
    return f"{amount:,.0f} {CURRENCY}"


def product_line(product: Product) -> str:
    """One product, one sentence, said the way a shopkeeper would say it."""
    if not product.available:
        return f"{product.name}, out of stock at the moment."

    line = f"{product.name}, {money(product.price)} for a {product.unit}"
    if product.in_stock <= 3:
        line += f", only {product.in_stock} left"
    if product.allergens:
        line += f". Contains {' and '.join(product.allergens)}"
    return line + "."


def product_card(product: Product) -> dict[str, Any]:
    """The screen version. Same facts, laid out rather than narrated."""
    return {
        "sku": product.sku,
        "title": product.name,
        "subtitle": f"{money(product.price)} / {product.unit}",
        "body": product.blurb,
        "category": product.category,
        "availability": "in stock" if product.available else "out of stock",
        "stock_remaining": product.in_stock,
        "allergens": product.allergens,
    }


def carousel(products: list[Product], offset: int = 0) -> dict[str, Any]:
    """A page of results: three spoken, all of them on the card carousel."""
    page = products[offset:offset + PAGE]
    remaining = max(0, len(products) - offset - len(page))

    if not page:
        spoken = "Nothing else here."
    else:
        spoken = " ".join(product_line(product) for product in page)
        if remaining:
            noun = "one more" if remaining == 1 else f"{remaining} more"
            spoken += f" There is {noun}. Say next to hear it."

    return {
        "speech": spoken,
        "cards": [product_card(product) for product in page],
        "offset": offset,
        "returned": len(page),
        "remaining": remaining,
        "total_matches": len(products),
    }


def cart_summary(cart: Cart) -> dict[str, Any]:
    """What is in the basket, and what it will cost at the door."""
    if cart.is_empty:
        return {
            "speech": "Your basket is empty.",
            "cards": [],
            "total": 0.0,
            "line_count": 0,
        }

    parts: list[str] = []
    cards: list[dict[str, Any]] = []
    for line in cart.lines:
        product = line.product
        if product is None:
            continue
        quantity = "" if line.quantity == 1 else f"{line.quantity} of "
        parts.append(f"{quantity}{product.name}")
        cards.append(
            {
                "sku": product.sku,
                "title": product.name,
                "subtitle": f"{line.quantity} x {money(product.price)}",
                "body": money(line.subtotal),
            }
        )

    listed = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
    speech = f"You have {listed}. That comes to {money(cart.total)}."

    heavy = [line.product.name for line in cart.lines
             if line.product and line.product.heavy]
    if heavy:
        speech += " Some of this is heavy, so the courier will need a hand at the door."

    return {
        "speech": speech,
        "cards": cards,
        "total": cart.total,
        "line_count": len(cart.lines),
    }


def confirmation_prompt(cart: Cart, address: str) -> str:
    """Read back before anything is ordered.

    A voice shopper cannot glance at a review page. This sentence is the
    review page, so it carries the two facts that cost money to get wrong:
    what they pay, and where it goes.
    """
    return (
        f"That is {money(cart.total)}, paid in cash to the courier, "
        f"delivered to {address}. Say yes to place the order."
    )
