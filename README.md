# VoiceCart

A whole storefront you can shop by voice: browse, hear products described,
fill a basket that is still there tomorrow, and order, without ever seeing a
screen.

A self-hosted **MCP server over Streamable HTTP**, built for the Alexa+ track
of the Amazon Developer Hackathon.

---

## Who this is for

Online shopping assumes you can see. Not the checkout, the whole thing: you
skim twenty results in two seconds, glance at a cart badge, scan a review
page before paying. Take sight away and every one of those becomes a
sentence somebody has to read to you, in order, with no skipping.

Screen readers make a shop *operable*. They do not make it *quick*. A blind
shopper working through a category page hears the navigation, the filters,
the promo banner and the cookie notice before the first product, and has no
way to skim past any of it.

A voice assistant can be quicker than a screen, not just an alternative to
one. But only if the shop on the other end is built for listening. That is
what this is.

## Built for listening, not for reading aloud

Most voice integrations take a screen-shaped API and read the JSON out. This
one is shaped by how hearing works.

**Three at a time, never twenty.** A sighted shopper skims a long list; a
listener cannot skip. So results come three at a time with the count of what
is left, and the assistant offers rather than continues.

```
Sylhet black tea, 320 taka for a 500 gram pack. Kalijira rice, 260 taka for a
2 kilo bag. Sundarban wild honey, 850 taka for a 500 gram jar. There is one
more. Say next to hear it.
```

**The disqualifying fact goes first.** "Out of stock" belongs before the
price, not after it, or the listener spends the whole sentence deciding to
buy something they cannot have.

```
Roasted cashew nuts, out of stock at the moment.
```

**The basket outlives the conversation.** A sighted shopper leaves a browser
tab open. A voice shopper has no tab, so state that dies with the session
means starting again every morning. Carts here are keyed to the shopper and
written to disk, which is also what lets `reorder_last` mean "the usual".

**One sentence is the review page.** There is no page to glance at before
paying, so the confirmation carries the two facts that cost money to get
wrong, and nothing else:

```
That is 10,450 taka, paid in cash to the courier, delivered to House 12,
Dhanmondi. Say yes to place the order.
```

`place_order` refuses to run without `confirmed=true`. Asking twice is not
friction here; it is the only review step that exists.

**Things you would have seen, said instead.** Allergens on food, every time.
A warning when the parcel is heavy enough that somebody should be at the
door. Low stock when there are three left. None of that is decoration on a
voice channel, it is the label you cannot pick up and read.

## Cash on delivery, and why that matters here

This shop is paid in cash when the courier arrives, which is how most of
South Asia buys online. It also removes the worst moment in voice commerce:
nobody is ever asked to say a card number out loud, in a room, to a device.
The server instructions tell the assistant never to ask for payment details
at all. There is nothing to pay until somebody knocks.

## The tools

Eleven small tools rather than one large `shop` tool, because a conversation
arrives one intent at a time and changes its mind between them.

| Tool | What it does |
| --- | --- |
| `list_categories` | The departments, spoken as a question |
| `browse_category` | A department, three products at a time |
| `search_products` | Whole spoken words, in-stock first |
| `describe_product` | The longer description, on request |
| `add_to_cart` | Clamped to real stock, never oversells |
| `remove_from_cart` | Takes it back out |
| `read_cart` | Reads the basket, including yesterday's |
| `review_order` | The spoken review page. Places nothing |
| `place_order` | Cash on delivery, refuses without confirmation |
| `order_status` | Where it has reached, in plain words |
| `reorder_last` | What "the usual" means |

Every one returns the same shape: `speech` to read aloud exactly as written,
and `cards` to render only if there is a screen. Both are declared in the
output schema, so a client knows there is a carousel to show without being
told in prose.

Search matches whole spoken words, not substrings. Somebody says "honey",
never "hon", and a substring match on "hon" would hand them honey as though
they had asked for it.

## Run it

```bash
pip install -r requirements.txt
python -m voicecart.server          # http://127.0.0.1:8080/mcp
```

Point any MCP client at `/mcp`. The server negotiates protocol `2025-11-25`.

Then watch a whole visit play out as a conversation:

```bash
python demo.py
```

```
  you    Then nine of the brass lamp.
         -> add_to_cart(sku='LMP-007', quantity=9)
  alexa  I could only add 3 of Brass table lamp, that is all there is.

  you    Order it to House 12, Dhanmondi.
         -> place_order(address='House 12, Dhanmondi')
  alexa  That is 10,450 taka, paid in cash to the courier, delivered to
         House 12, Dhanmondi. Say yes to place the order.
```

```bash
python -m pytest tests -q
```

Fifteen tests. Fourteen cover the shop rules directly. The fifteenth starts
the server as its own process and drives a whole shopping trip through the
MCP client over Streamable HTTP, so the transport, the protocol version, the
tool schemas and the rules are all exercised together.

## How it fits a real shop

`catalogue.py` is the only file that knows where products come from. It
reads a JSON catalogue shaped like a WooCommerce product payload, so
pointing this at a live store is one function, not a rewrite. Carts and
orders are equally isolated behind `carts.py` and `orders.py`.

## Layout

```
demo.py          a whole visit, played out on the terminal
voicecart/
  server.py      the MCP server and its eleven tools
  models.py      the reply shape every tool declares
  speech.py      products turned into something worth hearing
  catalogue.py   the storefront
  carts.py       baskets that outlive the conversation
  orders.py      placing and tracking, cash on delivery
data/
  catalogue.json the demo shop
tests/
  test_voicecart.py    the shop rules
  test_mcp_session.py  a whole trip over Streamable HTTP
```

## Licence

MIT. See [LICENSE](LICENSE).
