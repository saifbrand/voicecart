"""Reading a real shop, against a fake one.

The mapping is the risky part, not the HTTP. A WooCommerce payload is written
for a page, so it arrives with HTML in the description, prices as strings,
stock as either a number or a word, and nothing at all where a voice shopper
needs an allergen. Every case below is one a real shop actually produces.

The fake shop is stdlib only, so these run offline.
"""
from __future__ import annotations

import base64
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from voicecart import woo

# One row of each awkward shape a real shop serves.
ROWS = [
    {
        "id": 11, "sku": "TEA-001", "name": "Sylhet black tea",
        "price": "320.00", "stock_quantity": 14, "weight": "0.5",
        "categories": [{"name": "Groceries"}],
        "short_description": "<p>Strong &amp; malty leaf.</p>\n<p>Two hundred cups.</p>",
        "attributes": [{"name": "Unit", "options": ["500 gram pack"]}],
    },
    {
        "id": 12, "sku": "NUT-004", "name": "Roasted cashew nuts",
        "price": "1150", "stock_status": "outofstock", "stock_quantity": None,
        "categories": [{"name": "Groceries"}],
        "short_description": "Lightly salted.",
        "attributes": [{"name": "Allergens", "options": ["tree nuts", "milk"]}],
    },
    {
        "id": 13, "sku": "LMP-007", "name": "Brass table lamp",
        "price": "3200", "stock_quantity": 3, "weight": "4.2",
        "categories": [{"name": "Home and bath"}],
        "description": "Turned brass base. Fabric shade.",
        "attributes": [],
    },
    {
        "id": 14, "sku": "VAR-000", "name": "Cotton kurta",
        "price": "", "stock_status": "instock",
        "categories": [{"name": "Clothing"}], "attributes": [],
    },
    {
        "id": 15, "sku": "", "name": "",
        "price": "100", "categories": [], "attributes": [],
    },
]


class FakeShop(BaseHTTPRequestHandler):
    orders: list[dict] = []

    def _send(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authorised(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        user, _, password = base64.b64decode(header[6:]).decode().partition(":")
        return user == "ck_test" and password == "cs_test"

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if not self._authorised():
            return self._send(401, {"message": "no"})
        if self.path.startswith("/wp-json/wc/v3/products"):
            return self._send(200, ROWS)
        self._send(404, {"message": "no such route"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorised():
            return self._send(401, {"message": "no"})
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        FakeShop.orders.append(body)
        self._send(201, {"id": 4242, "number": "4242"})

    def log_message(self, *args) -> None:
        pass


@pytest.fixture(scope="module")
def shop():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    server = HTTPServer(("127.0.0.1", port), FakeShop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield woo.WooConfig(
        base_url=f"http://127.0.0.1:{port}", key="ck_test", secret="cs_test"
    )
    server.shutdown()


# --- the mapping -----------------------------------------------------------

def test_html_never_reaches_the_speech_layer():
    product = woo.to_product(ROWS[0])
    assert "<p>" not in product.blurb
    assert "&amp;" not in product.blurb
    assert product.blurb == "Strong & malty leaf."


def test_only_the_first_sentence_is_kept():
    """A listener wants one sentence before deciding, not a paragraph."""
    assert "Two hundred cups" not in woo.to_product(ROWS[0]).blurb


def test_a_unit_attribute_becomes_the_spoken_unit():
    assert woo.to_product(ROWS[0]).unit == "500 gram pack"


def test_stock_status_covers_shops_that_do_not_count():
    """stock_quantity is null when stock management is off."""
    assert woo.to_product(ROWS[1]).in_stock == 0

    priced_and_uncounted = {**ROWS[1], "stock_status": "instock"}
    assert woo.to_product(priced_and_uncounted).in_stock > 0


def test_allergens_are_read_off_the_shop():
    assert woo.to_product(ROWS[1]).allergens == ["tree nuts", "milk"]


def test_weight_decides_whether_somebody_must_be_at_the_door():
    assert woo.to_product(ROWS[2]).heavy is True
    assert woo.to_product(ROWS[0]).heavy is False


def test_a_product_with_no_price_is_not_offered():
    """A variable parent prices at nothing. Offering it would mislead."""
    assert woo.to_product(ROWS[3]) is None


def test_a_nameless_row_is_not_offered():
    assert woo.to_product(ROWS[4]) is None


def test_a_missing_sku_falls_back_to_the_id():
    row = {**ROWS[0], "sku": None, "id": 99}
    assert woo.to_product(row).sku == "WC-99"


# --- talking to the shop ---------------------------------------------------

def test_the_shop_is_read_over_http(shop):
    products = woo.fetch_products(shop)
    assert {p.sku for p in products} == {"TEA-001", "NUT-004", "LMP-007"}


def test_an_order_is_written_back_as_cash_on_delivery(shop):
    FakeShop.orders.clear()
    products = {p.sku: p for p in woo.fetch_products(shop)}

    number = woo.place_order(
        [(products["TEA-001"], 2)], "House 12, Dhanmondi", config=shop
    )

    assert number == "4242"
    sent = FakeShop.orders[-1]
    assert sent["payment_method"] == "cod"
    assert sent["set_paid"] is False
    assert sent["line_items"] == [{"sku": "TEA-001", "quantity": 2}]
    assert sent["shipping"]["address_1"] == "House 12, Dhanmondi"


def test_a_spoken_address_is_never_split_up(shop):
    """Guessing which half is the street would put a parcel somewhere else."""
    FakeShop.orders.clear()
    products = {p.sku: p for p in woo.fetch_products(shop)}
    spoken = "House 4, Lane 3, Uttara Sector 7, Dhaka 1230"

    woo.place_order([(products["TEA-001"], 1)], spoken, config=shop)

    assert FakeShop.orders[-1]["billing"]["address_1"] == spoken


def test_bad_credentials_fail_loudly(shop):
    wrong = woo.WooConfig(base_url=shop.base_url, key="ck_test", secret="wrong")
    with pytest.raises(woo.WooError):
        woo.fetch_products(wrong)


def test_an_unreachable_shop_fails_loudly():
    nowhere = woo.WooConfig(base_url="http://127.0.0.1:1", key="k", secret="s")
    with pytest.raises(woo.WooError):
        woo.fetch_products(nowhere)


def test_missing_settings_say_which_ones(monkeypatch):
    for name in ("WOO_BASE_URL", "WOO_KEY", "WOO_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(woo.WooError) as caught:
        woo.WooConfig.from_env()
    assert "WOO_BASE_URL" in str(caught.value)
