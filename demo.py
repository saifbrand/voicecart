"""A shopping trip, played out loud on the terminal.

Point this at a running VoiceCart server and it walks through a whole visit
as a conversation: what the shopper says, what the assistant would say back,
and the tool call that produced it. Written to be screen-recorded.

    python -m voicecart.server          # in one terminal
    python demo.py                      # in another

Pass --fast to skip the typing pauses.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
BLUE = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"

# (what the shopper says, tool, arguments)
TRIP: list[tuple[str, str, dict]] = [
    ("What do you sell?", "list_categories", {}),
    ("Groceries.", "browse_category", {"category": "Groceries"}),
    ("What else is there?", "browse_category", {"category": "Groceries", "offset": 3}),
    ("Do you have honey?", "search_products", {"query": "honey"}),
    ("Tell me more about it.", "describe_product", {"sku": "HON-003"}),
    ("Add one.", "add_to_cart", {"sku": "HON-003", "quantity": 1}),
    ("And the cashews.", "add_to_cart", {"sku": "NUT-004", "quantity": 1}),
    ("Then nine of the brass lamp.", "add_to_cart", {"sku": "LMP-007", "quantity": 9}),
    ("What is in my basket?", "read_cart", {}),
    ("Order it to House 12, Dhanmondi.", "place_order",
     {"address": "House 12, Dhanmondi"}),
    ("Read that back to me.", "review_order", {"address": "House 12, Dhanmondi"}),
    ("Yes.", "place_order", {"address": "House 12, Dhanmondi", "confirmed": True}),
    ("Where is my order?", "order_status", {}),
    ("Order the usual again.", "reorder_last", {}),
]


def wrap(text: str, indent: str = "        ") -> str:
    words, line, out = text.split(), "", []
    for word in words:
        if len(line) + len(word) + 1 > 64:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    out.append(line)
    return f"\n{indent}".join(out)


async def run(url: str, pause: float) -> None:
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()

            print(f"\n{BOLD}VoiceCart{RESET}  {DIM}shop a storefront by voice{RESET}")
            print(f"{DIM}connected to {init.server_info.name} "
                  f"{init.server_info.version}, MCP protocol "
                  f"{init.protocol_version}, {len(tools.tools)} tools{RESET}\n")
            time.sleep(pause * 2)

            for said, tool, args in TRIP:
                print(f"{BLUE}  you   {RESET} {said}")
                time.sleep(pause)

                result = await session.call_tool(tool, args)
                reply = result.structured_content or {}
                colour = GREEN if reply.get("ok", True) else YELLOW

                print(f"{DIM}        -> {tool}({', '.join(f'{k}={v!r}' for k, v in args.items())}){RESET}")
                print(f"{colour}  alexa {RESET} {wrap(reply.get('speech', ''))}")

                cards = reply.get("cards") or []
                if cards:
                    shown = ", ".join(card["title"] for card in cards)
                    print(f"{DIM}        [{len(cards)} card(s) on screen: {shown}]{RESET}")
                print()
                time.sleep(pause * 2)

            print(f"{DIM}  Nothing here needed a screen.{RESET}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get(
        "VOICECART_URL", "http://127.0.0.1:8080/mcp"))
    parser.add_argument("--fast", action="store_true", help="no pauses")
    args = parser.parse_args()

    if sys.platform == "win32":
        os.system("")  # let the terminal interpret the colour codes

    try:
        asyncio.run(run(args.url, 0.0 if args.fast else 0.9))
    except Exception as exc:  # noqa: BLE001 - a demo should fail readably
        print(f"\nCould not reach {args.url}: {exc}")
        print("Start the server first:  python -m voicecart.server")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
