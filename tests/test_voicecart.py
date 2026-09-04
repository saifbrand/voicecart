"""What a voice shopper is protected from.

These run with no network and no MCP client: they exercise the shop rules
directly, because those rules are the product. The end-to-end MCP journey
lives in test_mcp_session.py.
"""
from __future__ import annotations

import pytest

from voicecart import carts, catalogue, orders, speech


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Give every test its own cart and order files."""
    monkeypatch.setattr(carts, "CART_FILE", tmp_path / "carts.json")
    monkeypatch.setattr(orders, "ORDER_FILE", tmp_path / "orders.json")


def cart_with(*items: tuple[str, int]) -> carts.Cart:
    cart = carts.load("tester")
    for sku, quantity in items:
        cart.add(sku, quantity)
    return cart


# --- the catalogue ---------------------------------------------------------

def test_search_matches_spoken_words_not_fragments():
    """Somebody says "honey", never "hon"."""
    assert [p.sku for p in catalogue.search("honey")] == ["HON-003"]
    assert catalogue.search("hon") == []


def test_search_puts_what_you_can_actually_buy_first():
    results = catalogue.search("pack")
    in_stock = [p.available for p in results]
    assert in_stock == sorted(in_stock, reverse=True)


# --- the basket ------------------------------------------------------------

def test_out_of_stock_items_never_enter_the_basket():
    cart = cart_with(("NUT-004", 1))
    assert cart.is_empty


def test_quantity_is_clamped_to_what_exists():
    cart = cart_with(("LMP-007", 99))
    assert cart.find("LMP-007").quantity == catalogue.get("LMP-007").in_stock


def test_the_basket_survives_the_conversation():
    """The whole reason a voice shopper can pick up tomorrow."""
    carts.save(cart_with(("TEA-001", 2)))
    later = carts.load("tester")
    assert later.find("TEA-001").quantity == 2


# --- what gets said --------------------------------------------------------

def test_out_of_stock_is_said_before_the_price():
    """A listener cannot skim. The disqualifying fact goes first."""
    line = speech.product_line(catalogue.get("NUT-004"))
    assert line.index("out of stock") < len(line)
    assert "1,150" not in line


def test_allergens_are_always_spoken():
    cashews = catalogue.get("NUT-004")
    assert cashews.allergens
    in_stock_version = type(cashews)(**{**cashews.__dict__, "in_stock": 5})
    assert "tree nuts" in speech.product_line(in_stock_version)


def test_a_long_list_is_never_read_out_in_full():
    page = speech.carousel(catalogue.all_products())
    assert page["returned"] == speech.PAGE
    assert page["remaining"] == len(catalogue.all_products()) - speech.PAGE
    assert "Say next" in page["speech"]


def test_the_confirmation_carries_the_amount_and_the_address():
    """This sentence is the review page for somebody who cannot see one."""
    cart = cart_with(("TEA-001", 1))
    prompt = speech.confirmation_prompt(cart, "House 12, Dhanmondi")
    assert "320 taka" in prompt
    assert "House 12, Dhanmondi" in prompt
    assert "cash" in prompt


def test_heavy_orders_warn_that_somebody_must_be_there():
    cart = cart_with(("BSH-008", 1))
    assert "heavy" in speech.cart_summary(cart)["speech"]


# --- ordering --------------------------------------------------------------

def test_an_empty_basket_cannot_be_ordered():
    with pytest.raises(ValueError):
        orders.place(carts.load("tester"), "House 12, Dhanmondi")


def test_order_numbers_are_digits_only():
    """A shopper who cannot read the screen has to say this to a courier."""
    order = orders.place(cart_with(("TEA-001", 1)), "House 12, Dhanmondi")
    assert order.id.replace("-", "").isdigit()


def test_the_last_order_is_what_the_usual_means():
    cart = cart_with(("TEA-001", 1), ("HON-003", 1))
    orders.place(cart, "House 12, Dhanmondi")
    again = {p.sku for p in orders.reorderable("tester")}
    assert again == {"TEA-001", "HON-003"}


def test_a_sold_out_favourite_is_not_offered_again():
    cart = carts.load("tester")
    cart.lines.append(carts.Line(sku="NUT-004", quantity=1))
    orders.place(cart, "House 12, Dhanmondi")
    assert orders.reorderable("tester") == []
