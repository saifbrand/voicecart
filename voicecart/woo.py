"""Reading a real WooCommerce shop, and writing orders back to it.

Everything above this file speaks in `Product` and `Order`. This is the only
place that knows WooCommerce exists, so a shop swaps in by setting four
environment variables rather than by changing any of the voice logic.

The mapping is where the care is. A REST payload is written for a page, and
a page can afford to be vague: HTML in the description, a null price, a
stock field that is sometimes a number and sometimes the word "instock". A
listener cannot skim past any of that, so it is resolved here rather than
read out.
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass

import httpx

from voicecart.catalogue import Product

TAGS = re.compile(r"<[^>]+>")
WHITESPACE = re.compile(r"\s+")

# Above this, the courier needs somebody at the door.
HEAVY_KILOS = 3.0


class WooError(RuntimeError):
    """The shop could not be reached, or answered with something unusable."""


@dataclass(frozen=True)
class WooConfig:
    base_url: str
    key: str
    secret: str
    timeout: float = 15.0

    @classmethod
    def from_env(cls) -> "WooConfig":
        base = os.environ.get("WOO_BASE_URL", "").rstrip("/")
        key = os.environ.get("WOO_KEY", "")
        secret = os.environ.get("WOO_SECRET", "")
        if not (base and key and secret):
            raise WooError(
                "Set WOO_BASE_URL, WOO_KEY and WOO_SECRET to use a live shop."
            )
        return cls(base_url=base, key=key, secret=secret)

    @property
    def api(self) -> str:
        return f"{self.base_url}/wp-json/wc/v3"


def _client(config: WooConfig) -> httpx.Client:
    # WooCommerce accepts the key pair as basic auth over HTTPS, which keeps
    # the credentials out of the query string and therefore out of logs.
    return httpx.Client(
        base_url=config.api,
        auth=(config.key, config.secret),
        timeout=config.timeout,
        headers={"Accept": "application/json"},
    )


def plain(text: str | None) -> str:
    """A product description a person can listen to.

    Shop descriptions arrive as HTML written for a page: tags, entities, and
    line breaks that mean nothing out loud.
    """
    if not text:
        return ""
    stripped = TAGS.sub(" ", text)
    return WHITESPACE.sub(" ", html.unescape(stripped)).strip()


def first_sentence(text: str, limit: int = 160) -> str:
    """One sentence is all a listener wants before deciding."""
    clean = plain(text)
    if not clean:
        return ""
    head = re.split(r"(?<=[.!?])\s", clean)[0]
    return head if len(head) <= limit else head[:limit].rsplit(" ", 1)[0] + "..."


def to_product(row: dict) -> Product | None:
    """One WooCommerce product, resolved into something speakable.

    Returns None for rows this shop cannot sell by voice: no price, no name,
    or a variable parent whose real price lives on its children.
    """
    name = plain(row.get("name"))
    if not name:
        return None

    price_text = row.get("price") or row.get("regular_price") or ""
    try:
        price = float(price_text)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None

    stock = row.get("stock_quantity")
    if stock is None:
        # Stock management off: fall back to the coarse status flag.
        stock = 99 if row.get("stock_status") == "instock" else 0

    categories = row.get("categories") or [{}]
    weight_text = row.get("weight") or ""
    try:
        heavy = float(weight_text) >= HEAVY_KILOS
    except (TypeError, ValueError):
        heavy = False

    return Product(
        sku=(row.get("sku") or f"WC-{row.get('id')}").upper(),
        name=name,
        category=plain(categories[0].get("name")) or "Everything else",
        price=price,
        unit=_unit(row),
        in_stock=int(stock),
        blurb=first_sentence(row.get("short_description") or row.get("description")),
        allergens=_allergens(row),
        heavy=heavy,
    )


def _unit(row: dict) -> str:
    """What one of these is, said the way a shopkeeper would say it."""
    for attribute in row.get("attributes") or []:
        if plain(attribute.get("name")).casefold() in {"unit", "size", "pack size"}:
            options = attribute.get("options") or []
            if options:
                return plain(options[0])
    weight = row.get("weight")
    return f"{weight} kilo" if weight else "one"


def _allergens(row: dict) -> list[str]:
    """Allergens are a spoken safety fact, so they are read off the shop.

    WooCommerce has no allergen field, so shops put them in an attribute.
    Anything not found is reported as nothing found, never as none present:
    the speech layer says what the shop knows, and a silent shop is not the
    same as a safe product.
    """
    for attribute in row.get("attributes") or []:
        if plain(attribute.get("name")).casefold() in {"allergens", "allergen"}:
            return [plain(option) for option in attribute.get("options") or []]
    return []


def fetch_products(config: WooConfig | None = None, limit: int = 100) -> list[Product]:
    """Every sellable product in the shop."""
    config = config or WooConfig.from_env()
    try:
        with _client(config) as client:
            response = client.get(
                "/products",
                params={"per_page": min(limit, 100), "status": "publish"},
            )
            response.raise_for_status()
            rows = response.json()
    except httpx.HTTPError as exc:
        raise WooError(f"Could not reach the shop: {exc}") from exc

    products = [to_product(row) for row in rows]
    return [product for product in products if product is not None]


def place_order(
    lines: list[tuple[Product, int]],
    address: str,
    customer_name: str = "Voice shopper",
    config: WooConfig | None = None,
) -> str:
    """Write a cash-on-delivery order into the shop. Returns its number.

    The address arrives as one spoken line, because that is how somebody
    says it. Splitting a spoken address into WooCommerce's separate fields
    would mean guessing, so it goes in whole and the courier reads it whole.
    """
    config = config or WooConfig.from_env()
    payload = {
        "payment_method": "cod",
        "payment_method_title": "Cash on delivery",
        "set_paid": False,
        "billing": {"first_name": customer_name, "address_1": address},
        "shipping": {"first_name": customer_name, "address_1": address},
        "line_items": [
            {"sku": product.sku, "quantity": quantity}
            for product, quantity in lines
        ],
        "customer_note": "Placed by voice through VoiceCart.",
    }

    try:
        with _client(config) as client:
            response = client.post("/orders", json=payload)
            response.raise_for_status()
            created = response.json()
    except httpx.HTTPError as exc:
        raise WooError(f"The shop would not take the order: {exc}") from exc

    return str(created.get("number") or created.get("id"))
