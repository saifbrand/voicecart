"""VoiceCart MCP server, served over Streamable HTTP.

Every tool answers with the same shape: `speech`, one or two sentences meant
to be heard once, and `cards`, the same facts laid out for a screen when the
device has one. Alexa+ speaks the first and renders the second.

The tools are deliberately small and stateful rather than one large "shop"
tool. A voice conversation arrives one intent at a time, and the assistant
needs to be able to change its mind between them.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from mcp.server.mcpserver import AcceptedElicitation, Context, MCPServer
from mcp.types import Completion
from pydantic import BaseModel, Field

from voicecart import carts, catalogue, orders, refer, speech, subscriptions
from voicecart import repair as corrections
from voicecart.models import VoiceReply

DEFAULT_SHOPPER = "demo-shopper"

server = MCPServer(
    name="voicecart",
    title="VoiceCart",
    version="0.1.0",
    instructions=(
        "A storefront you can shop entirely by voice. Read the `speech` field "
        "aloud as written; it is already shaped for listening. Render `cards` "
        "only when the device has a screen.\n\n"
        "Three rules this shop expects you to keep:\n"
        "1. Never read more than one page of results at a time. Ask before "
        "continuing.\n"
        "2. Never place an order without calling review_order first and "
        "hearing the shopper agree. place_order refuses without it.\n"
        "3. This shop is cash on delivery. Never ask for a card, a bank "
        "account, or any payment detail. There is nothing to pay until the "
        "courier arrives.\n\n"
        "When the shopper corrects themselves - \"no, not that one\", \"take "
        "the last one back\", \"start again\" - send their words to repair "
        "rather than working out the undo yourself."
    ),
)

# Serve `resources/subscribe`, so a client can be told when a basket changes
# rather than polling the resource. See voicecart/subscriptions.py.
subscriptions.install(server)


def _cart(shopper_id: str) -> carts.Cart:
    return carts.load(shopper_id or DEFAULT_SHOPPER)


def _shown(reply: VoiceReply, shopper_id: str) -> VoiceReply:
    """Remember what was just read out, so it can be referred back to.

    Every list the shopper hears becomes the thing "the second one" and
    "the honey" point at. Without this, a voice shopper has to name a SKU.
    """
    skus = [card.sku for card in reply.cards if card.sku]
    if skus:
        refer.remember(shopper_id or DEFAULT_SHOPPER, skus)
    return reply


def _pick(item: str, shopper_id: str) -> tuple[str | None, VoiceReply | None]:
    """Resolve what the shopper said, or hand back the question to ask."""
    shopper = shopper_id or DEFAULT_SHOPPER
    found = refer.resolve(item, shopper)
    if found.found:
        # Remember what their words were taken to mean, so "no, not that
        # one" has something to point at.
        refer.note_resolved(shopper, found.sku)
        return found.sku, None
    return None, VoiceReply(speech=found.reason, ok=False)


async def _ask_to_confirm(
    ctx: Context | None, cart: carts.Cart, address: str
) -> bool | None:
    """Put the order to the shopper through the protocol, if we can.

    Returns True or False when the shopper answered, and None when the
    client cannot ask, in which case the caller hands the question back for
    the assistant to put in its own words.

    Elicitation is optional in MCP, so this is written to degrade rather
    than fail: an order is still never placed without a yes, it is only the
    route the question travels that changes.
    """
    if ctx is None:
        return None

    capabilities = ctx.client_capabilities
    if capabilities is None or capabilities.elicitation is None:
        return None

    try:
        answer = await ctx.elicit(
            message=speech.confirmation_prompt(cart, address),
            schema=Confirmation,
        )
    except Exception:  # noqa: BLE001 - never let asking cost somebody an order
        return None

    if isinstance(answer, AcceptedElicitation):
        return bool(answer.data.place_the_order)
    return False


@server.tool()
def list_categories() -> VoiceReply:
    """List the departments in the shop."""
    names = catalogue.categories()
    listed = ", ".join(names[:-1]) + f" and {names[-1]}"
    return VoiceReply(
        speech=f"The shop has {listed}. Which one?",
        cards=[{"title": name} for name in names],
        categories=names,
    )


@server.tool()
def browse_category(
    category: str, offset: int = 0, shopper_id: str = DEFAULT_SHOPPER
) -> VoiceReply:
    """Read out the products in one department, three at a time.

    Pass the offset returned by the previous call to hear the next three.
    """
    found = catalogue.in_category(category)
    if not found:
        known = ", ".join(catalogue.categories())
        return VoiceReply(
            speech=f"There is no {category} section. We have {known}.",
            ok=False,
        )
    return _shown(VoiceReply(**speech.carousel(found, offset)), shopper_id)


@server.tool()
def search_products(
    query: str, offset: int = 0, shopper_id: str = DEFAULT_SHOPPER
) -> VoiceReply:
    """Find products by what the shopper called them, three at a time."""
    found = catalogue.search(query)
    if not found:
        return VoiceReply(
            speech=f"I could not find anything for {query}.",
            ok=False,
        )
    return _shown(VoiceReply(**speech.carousel(found, offset)), shopper_id)


@server.tool()
def describe_product(item: str, shopper_id: str = DEFAULT_SHOPPER) -> VoiceReply:
    """Everything about one product, for when the shopper asks to hear more.

    `item` is whatever they said: a SKU, a position in the list you just read
    out ("the second one"), or a name ("the honey").
    """
    sku, problem = _pick(item, shopper_id)
    if problem is not None:
        return problem

    product = catalogue.get(sku)
    lines = [speech.product_line(product), product.blurb]
    if product.heavy:
        lines.append("It is heavy, so someone should be there to take it.")
    return _shown(
        VoiceReply(speech=" ".join(lines), cards=[speech.product_card(product)]),
        shopper_id,
    )


@server.tool()
async def add_to_cart(
    item: str,
    quantity: int = 1,
    shopper_id: str = DEFAULT_SHOPPER,
    ctx: Context | None = None,
) -> VoiceReply:
    """Put an item in the basket. Quantity is clamped to what is in stock.

    `item` is whatever they said: a SKU, a position in the list you just read
    out ("the second one"), or a name ("the honey"). When a phrase could mean
    more than one product, nothing is added and the reply asks which.
    """
    sku, problem = _pick(item, shopper_id)
    if problem is not None:
        return problem

    product = catalogue.get(sku)
    if not product.available:
        return VoiceReply(speech=f"{product.name} is out of stock.", ok=False)

    cart = _cart(shopper_id)
    asked = quantity
    now = cart.add(sku, quantity)
    carts.save(cart)
    await subscriptions.cart_changed(ctx, shopper_id or DEFAULT_SHOPPER)

    said = f"Added {product.name}."
    if now < asked:
        said = f"I could only add {now} of {product.name}, that is all there is."
    return VoiceReply(
        speech=f"{said} Your basket is now {speech.money(cart.total)}.",
        quantity_in_cart=now,
        cart_total=cart.total,
        line_count=len(cart.lines),
    )


@server.tool()
async def remove_from_cart(
    item: str, shopper_id: str = DEFAULT_SHOPPER, ctx: Context | None = None
) -> VoiceReply:
    """Take an item back out of the basket.

    `item` is whatever they said. "Take out the second one" resolves against
    the basket as it was just read, not against the shop.
    """
    cart = _cart(shopper_id)
    if not cart.is_empty:
        refer.remember(shopper_id or DEFAULT_SHOPPER, [line.sku for line in cart.lines])

    sku, problem = _pick(item, shopper_id)
    if problem is not None:
        return problem

    product = catalogue.get(sku)
    removed = cart.remove(sku)
    carts.save(cart)

    if not removed:
        return VoiceReply(speech="That was not in your basket.", ok=False)

    await subscriptions.cart_changed(ctx, shopper_id or DEFAULT_SHOPPER)

    name = product.name if product else "that item"
    return VoiceReply(
        speech=f"Removed {name}. Your basket is now {speech.money(cart.total)}.",
        cart_total=cart.total,
        line_count=len(cart.lines),
    )


@server.tool()
async def repair(
    said: str, shopper_id: str = DEFAULT_SHOPPER, ctx: Context | None = None
) -> VoiceReply:
    """Take back what the shopper says was wrong.

    Pass their correction word for word: "no, not that one", "take the last
    one back", "start again", "no, take the rice out". Speech corrects
    itself constantly, and a listener who cannot see the basket has no way
    to check what went in, so this is the one tool that walks the shop
    backwards.

    "Not that one" does two things: it undoes the change, and it stops the
    shop offering that product again for the same words.
    """
    shopper = shopper_id or DEFAULT_SHOPPER
    cart = _cart(shopper)
    intent = corrections.classify(said)

    if intent is corrections.Intent.CLEAR:
        if cart.is_empty:
            return VoiceReply(speech="Your basket is already empty.", ok=False)
        cart.empty()
        carts.save(cart)
        await subscriptions.cart_changed(ctx, shopper)
        return VoiceReply(
            speech="Emptied your basket. What would you like?",
            cart_total=0.0,
            line_count=0,
        )

    if intent in (corrections.Intent.UNDO, corrections.Intent.REJECT):
        was = {line.sku: line.quantity for line in cart.lines}
        if not cart.undo():
            return VoiceReply(
                speech="There is nothing to take back.",
                ok=False,
                cart_total=cart.total,
                line_count=len(cart.lines),
            )
        carts.save(cart)
        await subscriptions.cart_changed(ctx, shopper)

        # Name what actually went, rather than what the shop last thought
        # they meant: after "the usual", those are not the same thing.
        now = {line.sku: line.quantity for line in cart.lines}
        gone = [sku for sku, count in was.items() if now.get(sku, 0) < count]
        if intent is corrections.Intent.REJECT:
            for sku in gone:
                refer.reject(shopper, sku)

        names = [p.name for p in (catalogue.get(sku) for sku in gone) if p]
        undone = f"Took {' and '.join(names[:2])} back." if names else "Took that back."
        left = (
            "Your basket is empty."
            if cart.is_empty
            else f"Your basket is now {speech.money(cart.total)}."
        )
        asked = " What did you mean?" if intent is corrections.Intent.REJECT else ""
        return VoiceReply(
            speech=f"{undone} {left}{asked}",
            cart_total=cart.total,
            line_count=len(cart.lines),
        )

    if intent is corrections.Intent.REMOVE_NAMED:
        named = corrections.strip_correction(said)
        if named:
            return await remove_from_cart(item=named, shopper_id=shopper, ctx=ctx)

    return VoiceReply(speech="Take what back?", ok=False)


@server.tool()
def read_cart(shopper_id: str = DEFAULT_SHOPPER) -> VoiceReply:
    """Read the basket back.

    The basket outlives the conversation, so this is what makes "carry on
    from yesterday" work for somebody with no browser tab to leave open.
    """
    cart = _cart(shopper_id)
    summary = speech.cart_summary(cart)
    return _shown(
        VoiceReply(
            speech=summary["speech"],
            cards=summary["cards"],
            cart_total=summary["total"],
            line_count=summary["line_count"],
        ),
        shopper_id,
    )


@server.tool()
def review_order(address: str, shopper_id: str = DEFAULT_SHOPPER) -> VoiceReply:
    """Read the order back before placing it. Places nothing.

    This is the review page for somebody who cannot see one, so it carries
    the two facts that cost money to get wrong: the amount and the address.
    """
    cart = _cart(shopper_id)
    if cart.is_empty:
        return VoiceReply(
            speech="Your basket is empty, so there is nothing to order.",
            ok=False,
        )
    return VoiceReply(
        speech=speech.confirmation_prompt(cart, address),
        cards=speech.cart_summary(cart)["cards"],
        needs_confirmation=True,
        cart_total=cart.total,
        line_count=len(cart.lines),
        address=address,
    )


class Confirmation(BaseModel):
    """What the shopper is asked, when the client can ask on our behalf."""

    place_the_order: bool = Field(
        description="Yes to place this cash-on-delivery order, no to cancel."
    )


@server.tool()
async def place_order(
    address: str,
    confirmed: bool = False,
    shopper_id: str = DEFAULT_SHOPPER,
    ctx: Context | None = None,
) -> VoiceReply:
    """Place the order, cash on delivery.

    The order is never placed on the strength of the assistant's own
    judgement. Either `confirmed` is already true because the shopper heard
    review_order and said yes, or this asks them directly through the
    protocol's elicitation and waits for the answer.

    Nothing is charged now, so no payment detail is ever asked for.
    """
    cart = _cart(shopper_id)
    if cart.is_empty:
        return VoiceReply(speech="Your basket is empty.", ok=False)

    if not confirmed:
        agreed = await _ask_to_confirm(ctx, cart, address)
        if agreed is None:
            # The client cannot ask, so hand the question back for the
            # assistant to put to the shopper itself.
            return VoiceReply(
                speech=speech.confirmation_prompt(cart, address),
                needs_confirmation=True,
                ok=False,
                cart_total=cart.total,
                address=address,
            )
        if agreed is False:
            return VoiceReply(
                speech="Left it in your basket, nothing ordered.",
                ok=False,
                cart_total=cart.total,
            )

    order = orders.place(cart, address)
    cart.last_order_skus = [line.sku for line in cart.lines]
    cart.clear()
    carts.save(cart)
    await subscriptions.cart_changed(ctx, shopper_id or DEFAULT_SHOPPER)

    spoken_id = order.id.replace("-", ", ")
    return VoiceReply(
        speech=(
            f"Ordered. Your number is {spoken_id}. "
            f"{speech.money(order.total)} to the courier, "
            f"expected {orders.expected_delivery(order)}."
        ),
        order_id=order.id,
        stage=order.stage,
        cart_total=0.0,
        address=address,
    )


@server.tool()
def order_status(order_id: str = "", shopper_id: str = DEFAULT_SHOPPER) -> VoiceReply:
    """Where an order has reached. With no number, uses the most recent one."""
    order = orders.get(order_id) if order_id else orders.latest_for(shopper_id)
    if order is None:
        return VoiceReply(speech="I cannot find that order.", ok=False)

    spoken_id = order.id.replace("-", ", ")
    return VoiceReply(
        speech=(
            f"Order {spoken_id}. {order.spoken_stage} "
            f"Expected {orders.expected_delivery(order)}."
        ),
        order_id=order.id,
        stage=order.stage,
    )


@server.tool()
async def reorder_last(
    shopper_id: str = DEFAULT_SHOPPER, ctx: Context | None = None
) -> VoiceReply:
    """Refill the basket with the last order, which is what "the usual" means."""
    products = orders.reorderable(shopper_id)
    if not products:
        return VoiceReply(speech="You have not ordered anything yet.", ok=False)

    cart = _cart(shopper_id)
    for product in products:
        cart.add(product.sku, 1)
    carts.save(cart)
    await subscriptions.cart_changed(ctx, shopper_id or DEFAULT_SHOPPER)

    summary = speech.cart_summary(cart)
    return VoiceReply(
        speech=f"Put your last order back in the basket. {summary['speech']}",
        cards=summary["cards"],
        cart_total=summary["total"],
        line_count=summary["line_count"],
    )


# ---------------------------------------------------------------------------
# Resources: the shop as something to read, not only something to call.
#
# A tool call is an action. Reading the basket to decide what to say next is
# not an action, and an assistant should not have to invoke one to find out
# what it already knows. These are the same facts, addressable and cacheable,
# with no side effect attached.
# ---------------------------------------------------------------------------


@server.resource(
    "shop://catalogue",
    name="Catalogue",
    description="Every product in the shop, with price, unit and stock.",
    mime_type="application/json",
)
def catalogue_resource() -> str:
    return json.dumps(
        [speech.product_card(p) for p in catalogue.all_products()], indent=2
    )


@server.resource(
    "shop://category/{name}",
    name="Category",
    description="One department of the shop.",
    mime_type="application/json",
)
def category_resource(name: str) -> str:
    return json.dumps(
        [speech.product_card(p) for p in catalogue.in_category(name)], indent=2
    )


@server.resource(
    "shop://cart/{shopper_id}",
    name="Basket",
    description="What this shopper has in their basket right now.",
    mime_type="application/json",
)
def cart_resource(shopper_id: str) -> str:
    cart = _cart(shopper_id)
    return json.dumps(
        {
            "lines": [
                {"sku": line.sku, "quantity": line.quantity, "subtotal": line.subtotal}
                for line in cart.lines
            ],
            "total": cart.total,
        },
        indent=2,
    )


@server.resource(
    "shop://order/{order_id}",
    name="Order",
    description="One order and where it has reached.",
    mime_type="application/json",
)
def order_resource(order_id: str) -> str:
    order = orders.get(order_id)
    if order is None:
        return json.dumps({"error": "no such order"})
    return json.dumps(asdict(order), indent=2)


# ---------------------------------------------------------------------------
# Completion: help the assistant say a real category, rather than guess one.
# ---------------------------------------------------------------------------


@server.completion()
async def complete(ref, argument, context):
    """Suggest values for an argument the assistant is part way through.

    Only worth doing where the shop knows the answer and the assistant
    cannot: department names, and the products it just read out.
    """
    typed = (argument.value or "").casefold()

    if argument.name == "category":
        matches = [c for c in catalogue.categories() if c.casefold().startswith(typed)]
        return Completion(values=matches, total=len(matches), hasMore=False)

    if argument.name == "item":
        shopper = (context.arguments or {}).get("shopper_id") if context else None
        shown = refer.recent(shopper or DEFAULT_SHOPPER)
        names = [p.name for p in (catalogue.get(sku) for sku in shown) if p]
        if not names:
            names = [p.name for p in catalogue.all_products()]
        matches = [n for n in names if typed in n.casefold()][:10]
        return Completion(values=matches, total=len(matches), hasMore=False)

    return Completion(values=[], total=0, hasMore=False)


# ---------------------------------------------------------------------------
# Prompt: how to run this conversation, for a client that wants telling.
# ---------------------------------------------------------------------------


@server.prompt(
    name="shop_by_voice",
    title="Shop by voice",
    description="How to help somebody shop this store without a screen.",
)
def shop_by_voice_prompt(shopper_id: str = DEFAULT_SHOPPER) -> str:
    return "\n\n".join(
        [
            "You are helping somebody shop who is not looking at a screen.",
            f"Use shopper_id {shopper_id} on every call, so their basket is "
            "theirs and survives until tomorrow.",
            "Read the speech field back exactly. It is already the right "
            "length and says the disqualifying facts first. Do not summarise "
            "it, do not add the card contents to it, and never read a SKU "
            "aloud.",
            "When they refer to something by position or name, pass their "
            "words straight through as `item` and let the shop resolve them. "
            "If it answers with a question, ask that question rather than "
            "choosing for them.",
            "Before ordering, read review_order out and wait for a clear yes. "
            "Never ask for payment details: this shop is paid in cash at the "
            "door.",
        ]
    )


def main() -> None:
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(server.streamable_http_app(), host=host, port=port)


if __name__ == "__main__":
    main()
