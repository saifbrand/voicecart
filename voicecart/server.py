"""VoiceCart MCP server, served over Streamable HTTP.

Every tool answers with the same shape: `speech`, one or two sentences meant
to be heard once, and `cards`, the same facts laid out for a screen when the
device has one. Alexa+ speaks the first and renders the second.

The tools are deliberately small and stateful rather than one large "shop"
tool. A voice conversation arrives one intent at a time, and the assistant
needs to be able to change its mind between them.
"""
from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from voicecart import carts, catalogue, orders, speech
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
        "courier arrives."
    ),
)


def _cart(shopper_id: str) -> carts.Cart:
    return carts.load(shopper_id or DEFAULT_SHOPPER)


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
def browse_category(category: str, offset: int = 0) -> VoiceReply:
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
    return VoiceReply(**speech.carousel(found, offset))


@server.tool()
def search_products(query: str, offset: int = 0) -> VoiceReply:
    """Find products by what the shopper called them, three at a time."""
    found = catalogue.search(query)
    if not found:
        return VoiceReply(
            speech=f"I could not find anything for {query}.",
            ok=False,
        )
    return VoiceReply(**speech.carousel(found, offset))


@server.tool()
def describe_product(sku: str) -> VoiceReply:
    """Everything about one product, for when the shopper asks to hear more."""
    product = catalogue.get(sku)
    if product is None:
        return VoiceReply(speech="I cannot find that item.", ok=False)

    lines = [speech.product_line(product), product.blurb]
    if product.heavy:
        lines.append("It is heavy, so someone should be there to take it.")
    return VoiceReply(
        speech=" ".join(lines),
        cards=[speech.product_card(product)],
    )


@server.tool()
def add_to_cart(
    sku: str, quantity: int = 1, shopper_id: str = DEFAULT_SHOPPER
) -> VoiceReply:
    """Put an item in the basket. Quantity is clamped to what is in stock."""
    product = catalogue.get(sku)
    if product is None:
        return VoiceReply(speech="I cannot find that item.", ok=False)
    if not product.available:
        return VoiceReply(speech=f"{product.name} is out of stock.", ok=False)

    cart = _cart(shopper_id)
    asked = quantity
    now = cart.add(sku, quantity)
    carts.save(cart)

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
def remove_from_cart(sku: str, shopper_id: str = DEFAULT_SHOPPER) -> VoiceReply:
    """Take an item back out of the basket."""
    cart = _cart(shopper_id)
    product = catalogue.get(sku)
    removed = cart.remove(sku)
    carts.save(cart)

    if not removed:
        return VoiceReply(speech="That was not in your basket.", ok=False)

    name = product.name if product else "that item"
    return VoiceReply(
        speech=f"Removed {name}. Your basket is now {speech.money(cart.total)}.",
        cart_total=cart.total,
        line_count=len(cart.lines),
    )


@server.tool()
def read_cart(shopper_id: str = DEFAULT_SHOPPER) -> VoiceReply:
    """Read the basket back.

    The basket outlives the conversation, so this is what makes "carry on
    from yesterday" work for somebody with no browser tab to leave open.
    """
    summary = speech.cart_summary(_cart(shopper_id))
    return VoiceReply(
        speech=summary["speech"],
        cards=summary["cards"],
        cart_total=summary["total"],
        line_count=summary["line_count"],
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


@server.tool()
def place_order(
    address: str, confirmed: bool = False, shopper_id: str = DEFAULT_SHOPPER
) -> VoiceReply:
    """Place the order, cash on delivery.

    `confirmed` must be true, and it should only be true after the shopper
    has heard review_order and said yes. Nothing is charged now, so no
    payment detail is ever asked for.
    """
    cart = _cart(shopper_id)
    if cart.is_empty:
        return VoiceReply(speech="Your basket is empty.", ok=False)
    if not confirmed:
        return VoiceReply(
            speech=speech.confirmation_prompt(cart, address),
            needs_confirmation=True,
            ok=False,
            cart_total=cart.total,
            address=address,
        )

    order = orders.place(cart, address)
    cart.last_order_skus = [line.sku for line in cart.lines]
    cart.clear()
    carts.save(cart)

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
def reorder_last(shopper_id: str = DEFAULT_SHOPPER) -> VoiceReply:
    """Refill the basket with the last order, which is what "the usual" means."""
    products = orders.reorderable(shopper_id)
    if not products:
        return VoiceReply(speech="You have not ordered anything yet.", ok=False)

    cart = _cart(shopper_id)
    for product in products:
        cart.add(product.sku, 1)
    carts.save(cart)

    summary = speech.cart_summary(cart)
    return VoiceReply(
        speech=f"Put your last order back in the basket. {summary['speech']}",
        cards=summary["cards"],
        cart_total=summary["total"],
        line_count=summary["line_count"],
    )


def main() -> None:
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(server.streamable_http_app(), host=host, port=port)


if __name__ == "__main__":
    main()
