"""Taking things back, which is most of what real speech does.

The forward path was always testable by naming a product. These cover the
backward one: the shopper changing their mind mid-sentence, which is the
case a form never has to handle and a conversation always does.
"""
from __future__ import annotations

import pytest

from voicecart import carts, catalogue, orders, refer, server
from voicecart import repair as corrections

SHOPPER = "tester"


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(carts, "CART_FILE", tmp_path / "carts.json")
    monkeypatch.setattr(orders, "ORDER_FILE", tmp_path / "orders.json")
    monkeypatch.setattr(refer, "RECENT_FILE", tmp_path / "recent.json")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def a_grocery(index: int = 0) -> str:
    return catalogue.in_category("Groceries")[index].sku


# --- hearing the correction -----------------------------------------------

@pytest.mark.parametrize("said, intent", [
    ("no, not that one", corrections.Intent.REJECT),
    ("that's the wrong one", corrections.Intent.REJECT),
    ("I didn't mean that", corrections.Intent.REJECT),
    ("take the last one back", corrections.Intent.UNDO),
    ("undo that", corrections.Intent.UNDO),
    ("scratch that", corrections.Intent.UNDO),
    ("never mind", corrections.Intent.UNDO),
    ("start again", corrections.Intent.CLEAR),
    ("empty my basket", corrections.Intent.CLEAR),
    ("cancel everything", corrections.Intent.CLEAR),
    ("no, take the rice out", corrections.Intent.REMOVE_NAMED),
    ("", corrections.Intent.UNCLEAR),
])
def test_a_correction_is_understood_as_the_kind_it_is(said, intent):
    assert corrections.classify(said) is intent


def test_cancelling_everything_is_not_cancelling_one_thing():
    """"Cancel that" and "cancel everything" differ by one word and a basket."""
    assert corrections.classify("cancel that") is corrections.Intent.UNDO
    assert corrections.classify("cancel everything") is corrections.Intent.CLEAR


def test_the_apology_is_stripped_off_the_name():
    assert corrections.strip_correction("no, take the rice out") == "rice"
    assert corrections.strip_correction("sorry, remove the honey") == "honey"
    assert corrections.strip_correction("actually the bamboo pen") == "bamboo pen"


# --- taking a basket backwards --------------------------------------------

def test_undo_puts_the_basket_back_exactly_as_it_was():
    cart = carts.load(SHOPPER)
    first, second = a_grocery(0), a_grocery(1)
    cart.add(first, 1)
    cart.add(second, 2)

    assert cart.undo() is True
    assert [(line.sku, line.quantity) for line in cart.lines] == [(first, 1)]


def test_undo_survives_a_quantity_that_was_clamped():
    """An add is not reversible by subtracting: stock may have capped it."""
    product = next(p for p in catalogue.all_products() if 0 < p.in_stock <= 3)
    cart = carts.load(SHOPPER)
    cart.add(product.sku, 1)
    cart.add(product.sku, 99)  # clamped to whatever is on the shelf

    cart.undo()
    assert cart.find(product.sku).quantity == 1


def test_an_order_cannot_be_undone_back_into_the_basket():
    cart = carts.load(SHOPPER)
    cart.add(a_grocery(0), 1)
    cart.clear()  # what place_order does

    assert cart.can_undo is False
    assert cart.undo() is False


def test_what_can_be_taken_back_outlives_the_conversation():
    cart = carts.load(SHOPPER)
    cart.add(a_grocery(0), 1)
    carts.save(cart)

    tomorrow = carts.load(SHOPPER)
    assert tomorrow.can_undo is True
    tomorrow.undo()
    assert tomorrow.is_empty


# --- and through the tools -------------------------------------------------

@pytest.mark.anyio
async def test_take_the_last_one_back_empties_what_was_just_added():
    sku = a_grocery(0)
    await server.add_to_cart(item=sku, shopper_id=SHOPPER)

    reply = await server.repair(said="take the last one back", shopper_id=SHOPPER)

    assert reply.ok
    assert reply.line_count == 0
    assert catalogue.get(sku).name in reply.speech


@pytest.mark.anyio
async def test_nothing_to_take_back_says_so_rather_than_guessing():
    reply = await server.repair(said="undo that", shopper_id=SHOPPER)
    assert reply.ok is False
    assert "nothing to take back" in reply.speech


@pytest.mark.anyio
async def test_start_again_empties_the_basket_but_can_still_be_undone():
    await server.add_to_cart(item=a_grocery(0), shopper_id=SHOPPER)
    await server.add_to_cart(item=a_grocery(1), shopper_id=SHOPPER)

    cleared = await server.repair(said="start again", shopper_id=SHOPPER)
    assert cleared.ok and cleared.line_count == 0

    back = await server.repair(said="undo that", shopper_id=SHOPPER)
    assert back.ok and back.line_count == 2


@pytest.mark.anyio
async def test_not_that_one_stops_the_shop_offering_it_again():
    """The point of the rejection: the same words must land somewhere else."""
    ambiguous = _a_phrase_matching_two_products()
    if ambiguous is None:
        pytest.skip("this catalogue has no phrase that matches two products")
    phrase, first, second = ambiguous

    refer.remember(SHOPPER, [first, second])
    await server.add_to_cart(item=first, shopper_id=SHOPPER)

    refused = await server.repair(said="no, not that one", shopper_id=SHOPPER)
    assert refused.ok
    assert "What did you mean?" in refused.speech

    again = await server.add_to_cart(item=phrase, shopper_id=SHOPPER)
    assert again.ok, again.speech
    assert refer.rejected(SHOPPER) == [first]
    assert carts.load(SHOPPER).find(second) is not None


@pytest.mark.anyio
async def test_a_named_correction_takes_that_item_out():
    rice = next(p for p in catalogue.all_products() if "rice" in p.name.casefold())
    await server.add_to_cart(item=rice.sku, shopper_id=SHOPPER)
    await server.add_to_cart(item=a_grocery(0), shopper_id=SHOPPER)

    reply = await server.repair(said="no, take the rice out", shopper_id=SHOPPER)

    assert reply.ok, reply.speech
    assert carts.load(SHOPPER).find(rice.sku) is None


@pytest.mark.anyio
async def test_a_correction_nobody_could_act_on_asks_rather_than_guesses():
    await server.add_to_cart(item=a_grocery(0), shopper_id=SHOPPER)
    reply = await server.repair(said="hmm", shopper_id=SHOPPER)

    assert reply.ok is False
    assert not carts.load(SHOPPER).is_empty, "an unclear correction changes nothing"


def _a_phrase_matching_two_products():
    """A word two products share, so "not that one" has somewhere else to go."""
    for product in catalogue.all_products():
        for word in catalogue.words_of(product.name):
            matches = [
                other for other in catalogue.all_products()
                if catalogue.singular(word) in catalogue.words_of(other.name)
            ]
            if len(matches) == 2:
                return word, matches[0].sku, matches[1].sku
    return None
