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

That is measured, not asserted. Across seven live WooCommerce shops, read
through Chrome's own accessibility tree, **the median category page spends 98
words before it names a single product** - and one spends 270. VoiceCart
finishes an entire order in 119. The method, the numbers and the scripts that
produce them are in **[MEASUREMENT.md](MEASUREMENT.md)**.

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

**"The second one", because nobody says a SKU.** On a screen you point. In a
conversation you refer back, so the shop remembers the last list it read to
you and resolves against it.

```
  you    Show me the home and bath things.
  alexa  Neem and turmeric soap, 140 taka. Cotton hand towel, 480 taka.
         Brass table lamp, 3,200 taka, only 3 left. There is one more.

  you    Add the second one.
  alexa  Added Cotton hand towel, pair. Your basket is now 1,330 taka.
```

Positions, names and pointing all work, and the recent list wins over the
rest of the shop: two products have cotton in the name, but right after
hearing one of them, "add some cotton" is not ambiguous. When it genuinely
is, nothing is added and the reply asks which, because putting the wrong
thing in the basket of somebody who cannot see it is worse than asking
twice.

**Things you would have seen, said instead.** Allergens on food, every time.
A warning when the parcel is heavy enough that somebody should be at the
door. Low stock when there are three left. None of that is decoration on a
voice channel, it is the label you cannot pick up and read.

## More than a tool list

Most MCP servers expose tools and stop. This one uses the rest of the
protocol where the rest of the protocol is the right answer.

**Resources**, because reading is not an action. An assistant deciding what
to say next should not have to invoke something to find out what is already
true. `shop://catalogue`, `shop://category/{name}`, `shop://cart/{shopper}`
and `shop://order/{id}` are the same facts, addressable, with no side effect
attached.

**Subscriptions**, so a client watching `shop://cart/{shopper}` is told when
the basket stops being what it was, rather than polling to find out. The SDK
does not serve `resources/subscribe` at `2025-11-25`, so the shop registers
the handler itself - see `voicecart/subscriptions.py`, and the two entries it
earned in the friction log.

**Completion**, so the assistant says a department that exists rather than
guessing at one, and can complete an `item` against the products it just
read out.

**A prompt**, `shop_by_voice`, which tells a client how to run this
conversation: read the speech field exactly, pass the shopper's own words
through as `item`, never read a SKU aloud.

**Elicitation**, which is the interesting one. The order is never placed on
the assistant's own judgement. If the client can ask, the shop asks it
directly through the protocol and waits:

```
place_order(address="House 90, Bashundhara")
  -> elicit: "That is 320 taka, paid in cash to the courier, delivered to
              House 90, Bashundhara. Say yes to place the order."
  -> accepted: place_the_order = true
  <- "Ordered. Your number is 21, 8570."
```

Elicitation is optional in MCP, so this degrades rather than fails. A client
that cannot ask gets the same question handed back as speech, for the
assistant to put in its own words. Either way nothing is ordered without a
yes; only the route the question travels changes.

## Cash on delivery, and why that matters here

This shop is paid in cash when the courier arrives, which is how most of
South Asia buys online. It also removes the worst moment in voice commerce:
nobody is ever asked to say a card number out loud, in a room, to a device.
The server instructions tell the assistant never to ask for payment details
at all. There is nothing to pay until somebody knocks.

## Speech corrects itself

A person shopping out loud does not issue clean commands. They say "no, not
that one", "take the last one back", "start again" - and they say it halfway
through the sentence they are already in. A shop that only understands
forward motion makes the shopper carry the correction: remember what went in,
name it exactly, ask for it to come out.

So a correction is its own intent. `repair` takes the shopper's words
verbatim and walks the shop backwards:

| said | what happens |
| --- | --- |
| "take the last one back" | the basket goes back to what it was before the last change |
| "no, not that one" | the same undo, **and** that product stops being offered for those words |
| "start again" | the basket empties - and that can itself be taken back |
| "no, take the rice out" | the apology is stripped off and the rice comes out |

The undo is a snapshot of the whole basket, not a reversed operation, because
an add is not reversible on its own: it may have been clamped to what was in
stock, or merged into a line already there. Only an order cannot be undone -
handing somebody back a basket they have already bought would be a lie about
what they owe.

## The tools

Twelve small tools rather than one large `shop` tool, because a conversation
arrives one intent at a time and changes its mind between them.

| Tool | What it does |
| --- | --- |
| `list_categories` | The departments, spoken as a question |
| `browse_category` | A department, three products at a time |
| `search_products` | Whole spoken words, in-stock first |
| `describe_product` | The longer description, on request |
| `add_to_cart` | Clamped to real stock, never oversells |
| `remove_from_cart` | Takes it back out |
| `repair` | "No, not that one" - undoes, and stops offering it |
| `read_cart` | Reads the basket, including yesterday's |
| `review_order` | The spoken review page. Places nothing |
| `place_order` | Cash on delivery, refuses without confirmation |
| `order_status` | Where it has reached, in plain words |
| `reorder_last` | What "the usual" means |

Every one returns the same shape: `speech` to read aloud exactly as written,
and `cards` to render only if there is a screen. Both are declared in the
output schema, so a client knows there is a carousel to show without being
told in prose.

`describe_product`, `add_to_cart` and `remove_from_cart` take an `item`
phrase rather than a SKU: a position, a name, or a bare "that one" all
resolve, and an ambiguous phrase comes back as a question.

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
  you    Add the second one.
         -> add_to_cart(item='the second one')
  alexa  Added Cotton hand towel, pair. Your basket is now 1,330 taka.

  you    And nine of the brass lamp.
         -> add_to_cart(item='brass lamp', quantity=9)
  alexa  I could only add 3 of Brass table lamp, that is all there is.

  you    Order it to House 12, Dhanmondi.
         -> place_order(address='House 12, Dhanmondi')
  alexa  That is 10,450 taka, paid in cash to the courier, delivered to
         House 12, Dhanmondi. Say yes to place the order.
```

```bash
python -m pytest tests -q
```

Seventy five tests. Most cover the shop rules, the corrections and the
WooCommerce mapping directly. Four start the server as its own process and
drive it through a real MCP client over Streamable HTTP: a whole shopping
trip, an order confirmed by elicitation, an order declined, and a client
subscribing to a basket and being told when it changes. The transport, the
negotiated protocol version, the tool schemas and the shop rules are all
exercised together.

## Point it at a real shop

It already runs against live WooCommerce. Four settings, no code:

```bash
STORE_SOURCE=woocommerce
WOO_BASE_URL=https://your-shop.example
WOO_KEY=ck_...
WOO_SECRET=cs_...
```

Products are then read from the shop and orders are written back into it as
real cash-on-delivery orders, which appear in the shop's own order list.

The work is not the HTTP, it is the mapping. A WooCommerce payload is
written for a page, and a page can afford to be vague in ways a listener
cannot skim past:

| What the shop sends | What a listener gets |
| --- | --- |
| `<p>Strong &amp; malty leaf.</p>` and three more paragraphs | one sentence, no markup, no entities |
| `stock_quantity: null` because stock management is off | the `instock` flag, read as availability |
| `price: ""` on a variable parent | not offered at all, rather than offered at nothing |
| `weight: 4.2` | "someone should be there to take it" |
| an Allergens attribute | spoken every time, before the price |

A spoken address goes into the order whole. Splitting "House 4, Lane 3,
Uttara Sector 7" into WooCommerce's separate fields would mean guessing
which part is the street, and a wrong guess puts a parcel somewhere else.

`voicecart/woo.py` is the only file that knows WooCommerce exists. Sixteen
tests cover it against a fake shop that serves each awkward row a real store
produces, so they run offline.

## Layout

```
demo.py          a whole visit, played out on the terminal
voicecart/
  server.py      the MCP server and its twelve tools
  models.py      the reply shape every tool declares
  speech.py      products turned into something worth hearing
  refer.py       working out which product somebody meant
  repair.py      working out what somebody is taking back
  subscriptions.py  telling a client the basket changed
  woo.py         reading a live WooCommerce shop, and ordering from it
  catalogue.py   the storefront
  carts.py       baskets that outlive the conversation
  orders.py      placing and tracking, cash on delivery
data/
  catalogue.json the demo shop
measure/
  screen_reader_cost.py  what a shop says before its first product
  voice_cost.py          what this shop says for a whole order
tests/
  test_voicecart.py    the shop rules
  test_refer.py        what "the second one" means
  test_repair.py       taking things back
  test_subscriptions.py  who gets told, and who does not
  test_woo.py          the live shop, against a fake one
  test_mcp_session.py  a whole trip over Streamable HTTP
```

## Building this

[FRICTION-LOG.md](FRICTION-LOG.md) records what cost time while building
against the MCP Python SDK and the Alexa+ track: what I expected, what
happened, and what I would change. It includes the things that worked, and
the one gap that mattered most, which is that there is no way to test an
Alexa+ integration against Alexa+.

## Licence

MIT. See [LICENSE](LICENSE).
