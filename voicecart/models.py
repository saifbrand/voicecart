"""What every tool returns.

Declaring these as models rather than plain dicts gives each tool an output
schema, so the assistant on the other end knows there is a `speech` string to
read aloud and a `cards` list to render, without being told in prose. It is
the difference between a client that can show a product carousel and one that
reads JSON out loud.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Card(BaseModel):
    """One product, laid out for a screen."""

    title: str
    sku: str = ""
    subtitle: str = ""
    body: str = ""
    category: str = ""
    availability: str = ""
    stock_remaining: int = 0
    allergens: list[str] = Field(default_factory=list)


class VoiceReply(BaseModel):
    """The shape every tool answers with.

    `speech` is always present and always safe to read aloud unchanged.
    Everything else is context the assistant may use or ignore.
    """

    speech: str = Field(description="Read this aloud, exactly as written.")
    cards: list[Card] = Field(
        default_factory=list,
        description="Render only on a device with a screen. Never read aloud.",
    )

    ok: bool = Field(
        default=True,
        description="False when the request could not be carried out.",
    )
    needs_confirmation: bool = Field(
        default=False,
        description="True when the shopper must agree out loud before this proceeds.",
    )

    # Paging, so the assistant knows whether there is more to offer.
    offset: int = 0
    returned: int = 0
    remaining: int = 0
    total_matches: int = 0

    # Cart and order state.
    quantity_in_cart: int = 0
    cart_total: float = 0.0
    line_count: int = 0
    order_id: str = ""
    stage: str = ""
    address: str = ""

    categories: list[str] = Field(default_factory=list)
