"""How much a listener hears before they reach the first product.

VoiceCart's whole argument is that a screen reader makes a shop *operable*
but not *quick*: the page is announced in one long line, and a listener
cannot skim it the way an eye skims a grid. That is easy to assert and
worth nothing until it is counted, so this counts it.

The tree read here is Chrome's own accessibility tree, pulled over CDP -
the same tree NVDA, JAWS and VoiceOver are handed. Nothing is simulated:
what is counted is what the browser says is announceable, in document
order, and the count stops at the first product on the page.

Three numbers come out, because a fair comparison has to use the fast path
a real screen reader user knows, not only the slow one a first visit falls
into:

  linear      reading from the top, which is what happens on a first visit
  from main   after jumping to the main landmark (the D or R key)
  headings    how many heading stops away the first product is (the H key)

Usage:
    python -m measure.screen_reader_cost https://shop.example/product-category/tea
    python -m measure.screen_reader_cost --json measure/shops.json --out results.json
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import asdict, dataclass, field

from playwright.sync_api import sync_playwright

# Roles a screen reader announces as a unit: it says the name, then the role,
# and moves on. Their inner text is not read a second time, so the walk does
# not descend into them.
SELF_ANNOUNCING = {
    "link", "button", "heading", "checkbox", "radio", "textbox", "searchbox",
    "combobox", "listbox", "option", "menuitem", "menuitemcheckbox", "tab",
    "switch", "slider", "spinbutton", "image", "img", "figure",
}

# The role itself costs a word or two out loud: "Shop, link", "Sale, heading
# level two". Kept deliberately conservative - one word for most, two where
# the announcement genuinely is two.
ROLE_WORDS = {
    "heading": 2,      # "heading level two"
    "textbox": 2,      # "edit, blank"
    "searchbox": 2,
    "combobox": 2,     # "combo box"
    "checkbox": 2,     # "check box, not checked"
    "menuitem": 2,     # "menu item"
    "image": 1,
    "img": 1,
}

FOCUSABLE = {
    "link", "button", "checkbox", "radio", "textbox", "searchbox", "combobox",
    "menuitem", "menuitemcheckbox", "tab", "switch", "slider", "spinbutton",
}

MAIN_ROLES = {"main", "Main"}

# Every WooCommerce theme lays the grid out differently - list, block grid,
# page builder - but they all link to /product/, so the products are found by
# their links rather than by anybody's markup.
PRODUCT_LINK = "a[href*='/product/'], a[href*='/products/']"


@dataclass
class Stop:
    """One thing the screen reader says."""

    role: str
    name: str
    words: int
    focusable: bool


@dataclass
class Measurement:
    url: str
    ok: bool = True
    note: str = ""
    first_product: str = ""

    linear_stops: int = 0
    linear_words: int = 0
    linear_tab_stops: int = 0

    from_main_stops: int = 0
    from_main_words: int = 0

    headings_before: int = 0
    total_stops_on_page: int = 0

    one_product_words: int = 0
    three_products_words: int = 0

    preamble: list[str] = field(default_factory=list)


def words_in(text: str) -> int:
    return len([word for word in re.split(r"\s+", text.strip()) if word])


def spoken_cost(role: str, name: str) -> int:
    if role == "StaticText":
        return words_in(name)
    return words_in(name) + ROLE_WORDS.get(role, 1)


def role_of(node: dict) -> str:
    return (node.get("role") or {}).get("value", "") or ""


def name_of(node: dict) -> str:
    return (((node.get("name") or {}).get("value")) or "").strip()


def walk(nodes: dict, node_id, out: list[Stop], seen: set) -> None:
    """Collect what would be said, in the order it would be said."""
    if node_id in seen:
        return
    seen.add(node_id)

    node = nodes.get(node_id)
    if node is None:
        return

    role = role_of(node)
    name = name_of(node)

    # An ignored node says nothing itself, but Chrome ignores most plain
    # containers, and everything announceable hangs below them.
    if node.get("ignored"):
        for child in node.get("childIds", []):
            walk(nodes, child, out, seen)
        return

    if name and role in SELF_ANNOUNCING:
        out.append(Stop(role, name, spoken_cost(role, name), role in FOCUSABLE))
        return  # announced whole; its inner text is not read again
    if role == "StaticText" and name:
        out.append(Stop(role, name, words_in(name), False))
        return

    for child in node.get("childIds", []):
        walk(nodes, child, out, seen)


def find_main(nodes: dict, node_id, seen: set):
    if node_id in seen:
        return None
    seen.add(node_id)
    node = nodes.get(node_id)
    if node is None:
        return None
    if role_of(node) in MAIN_ROLES:
        return node_id
    for child in node.get("childIds", []):
        hit = find_main(nodes, child, seen)
        if hit is not None:
            return hit
    return None


def index_of_main(stops: list[Stop], nodes: dict, root) -> int:
    """Where the main landmark starts, in the flat list of announcements."""
    main_id = find_main(nodes, root, set())
    if main_id is None:
        return 0

    inside: list[Stop] = []
    walk(nodes, main_id, inside, set())
    if not inside:
        return 0

    first = inside[0]
    for index, stop in enumerate(stops):
        if stop.name == first.name and stop.role == first.role:
            return index
    return 0


def normalise(text: str) -> str:
    """Compare names the way an ear would, not the way a byte would."""
    lowered = text.casefold()
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def product_titles(page) -> list[str]:
    """The product names on this page, taken from the links themselves."""
    found = page.eval_on_selector_all(
        PRODUCT_LINK,
        """(links) => links.map((link) => [
             (link.innerText || link.textContent || '').trim().split('\\n')[0].trim(),
             link.getAttribute('href') || '',
           ])""",
    )
    seen: list[str] = []
    for name, href in found:
        # A category or tag archive is not a thing you can buy.
        if any(part in href for part in NOT_A_PRODUCT_HREF):
            continue
        cleaned = (name or "").strip()
        # "Add to cart", "Select options" and prices are links inside a card,
        # not the name of the thing being sold. Some themes leave escaped
        # image markup as the link text, which is not a name either.
        if len(cleaned) < 4 or len(cleaned) > 120 or "<" in cleaned:
            continue
        if normalise(cleaned) in IGNORED_LINK_TEXT:
            continue
        if cleaned not in seen:
            seen.append(cleaned)
    return seen


NOT_A_PRODUCT_HREF = (
    "product-category", "product-tag", "product_cat", "product_tag",
    "/category/", "add-to-cart", "?", "#",
)

IGNORED_LINK_TEXT = {
    "add to cart", "select options", "read more", "buy now", "view product",
    "quick view", "add to basket", "shop now", "learn more", "details",
    "add to wishlist", "compare", "sale", "out of stock", "view details",
}


def matches_product(stop_name: str, products: list[str]) -> str | None:
    """Is this announcement one of the products?

    A theme may put the whole name in the link, or truncate it, or wrap it
    with a price. So a match either way round counts, as long as it is more
    than a couple of words - otherwise a nav item called "Tea" would pass
    for a product called "Tea".
    """
    said = normalise(stop_name)
    if len(said.split()) < 2:
        return None
    for product in products:
        wanted = normalise(product)
        if len(wanted.split()) < 2:
            continue
        if wanted in said or said in wanted:
            return product
    return None


def measure(page, url: str) -> Measurement:
    result = Measurement(url=url)

    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:  # noqa: BLE001 - a chatty page is still measurable
        pass

    products = product_titles(page)
    if len(products) < 3:
        result.ok = False
        result.note = "no product grid found on this page"
        return result

    cdp = page.context.new_cdp_session(page)
    cdp.send("Accessibility.enable")
    tree = cdp.send("Accessibility.getFullAXTree")
    nodes = {node["nodeId"]: node for node in tree["nodes"]}
    root = tree["nodes"][0]["nodeId"]

    stops: list[Stop] = []
    walk(nodes, root, stops, set())
    result.total_stops_on_page = len(stops)

    main_at = index_of_main(stops, nodes, root)

    # The first product *in the grid*. A shop that lists products in its nav
    # would otherwise make its own preamble look shorter than it is, so the
    # search starts at the main landmark.
    hits = [
        (index, matches_product(stop.name, products))
        for index, stop in enumerate(stops)
        if index >= main_at
    ]
    found = [(index, name) for index, name in hits if name]
    if not found:
        result.ok = False
        result.note = "no product name was announced anywhere in the tree"
        return result

    cut, first_name = found[0]
    result.first_product = first_name

    before = stops[:cut]
    result.linear_stops = len(before)
    result.linear_words = sum(stop.words for stop in before)
    result.linear_tab_stops = sum(1 for stop in before if stop.focusable)
    result.headings_before = sum(1 for stop in before if stop.role == "heading")
    result.preamble = [f"{stop.name} ({stop.role})" for stop in before[:12]]

    from_main = stops[main_at:cut] if main_at < cut else []
    result.from_main_stops = len(from_main)
    result.from_main_words = sum(stop.words for stop in from_main)

    # What one product costs to hear, and what comparing three costs: the
    # everyday act a sighted shopper does in one glance.
    later = [index for index, name in found if index > cut and name != first_name]
    if later:
        result.one_product_words = sum(stop.words for stop in stops[cut:later[0]])
        result.three_products_words = result.one_product_words * 3
    return result


def report(results: list[Measurement]) -> None:
    good = [r for r in results if r.ok]
    for result in results:
        print(f"\n{result.url}")
        if not result.ok:
            print(f"  skipped: {result.note}")
            continue
        print(f"  first product           {result.first_product}")
        print(f"  linear to first product {result.linear_words} words "
              f"over {result.linear_stops} stops "
              f"({result.linear_tab_stops} of them focusable)")
        print(f"  from the main landmark  {result.from_main_words} words "
              f"over {result.from_main_stops} stops")
        print(f"  headings to skip past   {result.headings_before}")
        if result.one_product_words:
            print(f"  one product costs       {result.one_product_words} words "
                  f"({result.three_products_words} to compare three)")
        if result.preamble:
            print(f"  first said: {'; '.join(result.preamble[:6])}")

    if len(good) > 1:
        print("\n--- across all shops measured ---")
        for label, values in (
            ("linear words to the first product", [r.linear_words for r in good]),
            ("words after jumping to main", [r.from_main_words for r in good]),
            ("focusable stops before the first product",
             [r.linear_tab_stops for r in good]),
            ("words to compare three products",
             [r.three_products_words for r in good if r.three_products_words]),
        ):
            if values:
                print(f"  {label}: median {statistics.median(values):.0f}, "
                      f"range {min(values)}-{max(values)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Count what a screen reader says.")
    parser.add_argument("urls", nargs="*", help="category pages to measure")
    parser.add_argument("--json", help="file holding a list of URLs")
    parser.add_argument("--out", help="write the raw measurements here")
    parser.add_argument("--headed", action="store_true", help="watch it work")
    args = parser.parse_args()

    urls = list(args.urls)
    if args.json:
        with open(args.json, encoding="utf-8") as handle:
            urls += json.load(handle)
    if not urls:
        parser.error("give at least one category page URL")

    results: list[Measurement] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        for url in urls:
            try:
                results.append(measure(page, url))
            except Exception as error:  # noqa: BLE001 - one bad shop is not fatal
                results.append(Measurement(url=url, ok=False, note=str(error)[:200]))
        browser.close()

    report(results)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump([asdict(result) for result in results], handle, indent=2)
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
