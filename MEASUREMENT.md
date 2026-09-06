# The claim, measured

VoiceCart is built on one assertion: **a screen reader makes a shop operable,
not quick.** A listener cannot skim. Everything in the design — three results
at a time, the disqualifying fact first, one sentence carrying the whole
review page — follows from that.

An assertion is worth nothing until somebody counts it, so this counts it.

## What was counted, and how

Two scripts, both in [`measure/`](measure/), both measuring the same thing in
the same unit: **words a person has to listen to.**

`measure/screen_reader_cost.py` opens a real WooCommerce category page in
Chrome, pulls **Chrome's own accessibility tree over CDP** — the tree NVDA,
JAWS and VoiceOver are handed — and walks it in document order, counting
every announcement until the first product is named. Nothing is simulated or
estimated: what is counted is what the browser says is announceable.

Because a fair comparison has to use the fast path a real screen reader user
knows, three numbers come out of every page:

| number | what it means |
| --- | --- |
| **linear** | reading from the top, which is what a first visit gets |
| **from main** | after jumping to the `main` landmark (the <kbd>D</kbd> or <kbd>R</kbd> key) |
| **headings** | how many heading stops away the first product is (<kbd>H</kbd>) |

`measure/voice_cost.py` runs a whole order through VoiceCart's real tools and
counts the words in the `speech` strings the assistant is told to read aloud.
No mock, no transcript, no rounding.

Seven live WooCommerce shops were measured on 6 September 2026: two vendor
stores named below, and five independent retailers left anonymous — the point
is what the platform does by default, not which shop to blame.

## What came back

### Before you reach the first product

| shop | linear words | after jumping to main | focusable stops | headings to skip |
| --- | ---: | ---: | ---: | ---: |
| woocommerce.com (extensions) | 270 | 200 | 64 | 2 |
| Shop A — clothing, Bangladesh | 248 | 205 | 59 | 4 |
| Shop B — guitar pedal parts | 205 | 55 | 16 | 1 |
| Shop C — butcher, USA | 98 | 98 | 22 | 1 |
| kadencewp.com (plugins) | 97 | 11 | 19 | 2 |
| Shop D — coffee and spices | 59 | 14 | 15 | 1 |
| Shop E — supplements | 52 | 26 | 11 | 2 |
| **median** | **98** | **55** | **19** | **2** |

**VoiceCart: 0.** The reply opens with the product. There is nothing in front
of it, because there is no page in front of it.

The first six things one of those shops said, in order, before any product:

> Manage Consent · Close dialog · *"To provide the best experiences, we use
> technologies like cookies to store and/or access device information.
> Consenting to these technologies will allow us to process data such as
> browsing behaviour or unique IDs on this site…"* · ACCEPT · Opt-out
> preferences · Skip to content

That cookie paragraph alone is 55 words. A sighted shopper's eye crosses it in
about a fifth of a second. A listener hears all of it.

### Comparing three products

The everyday act — hearing three things and picking one.

| | words |
| --- | ---: |
| shop page, three products announced | **93** (median; range 57–150) |
| VoiceCart, three products spoken | **40** |

### A whole order

Every word VoiceCart says, from the first question to the order number:

| said | words | heard |
| --- | ---: | --- |
| "what have you got" | 12 | The shop has Groceries, Home and bath, Clothing and Stationery. Which one? |
| "show me the groceries" | 40 | Sylhet black tea, loose leaf, 320 taka for a 500 gram pack. Kalijira rice, 260 taka for a 2 kilo bag. Sundarban wild honey, 850 taka for a 500 gram jar. There is one more. Say next to hear it. |
| "add the second one" | 9 | Added Kalijira rice. Your basket is now 260 taka. |
| "what is in my basket" | 24 | You have Kalijira rice. That comes to 260 taka. Some of this is heavy, so the courier will need a hand at the door. |
| "house twelve, Dhanmondi" | 21 | That is 260 taka, paid in cash to the courier, delivered to House 12, Dhanmondi. Say yes to place the order. |
| "yes" | 13 | Ordered. Your number is 26, 3408. 260 taka to the courier, expected Tuesday. |
| **total** | **119** | |

## The two numbers

> **The median WooCommerce category page spends 98 words before it names a
> single product. VoiceCart finishes an entire order in 119.**

> **One shop in the sample spent 270 words getting to its first product —
> more than twice what a whole order costs here.**

Both are measured, not asserted, and either script re-runs against any shop on
the web in under a minute.

## What this does not claim

- **These shops are not broken.** Every one is operable with a screen reader,
  and several have skip links, landmarks and honest headings. That is the
  point: they follow the rules and are still slow, because the cost is in the
  shape of a page, not in a missing attribute.
- **The fast path was counted too.** Jumping straight to `main` still costs a
  median 55 words, and on the two worst shops 200 and 205.
- **Word counts are a proxy for time, not time itself.** Synthesised speech
  runs roughly 150–200 words a minute, so 98 words is about 30–40 seconds
  before the first product. Rate varies by listener and by voice, so the
  count is reported rather than a time.
- **Sample size is seven.** Enough to show the size of the problem, not
  enough to publish a distribution. The tool is in the repo precisely so the
  number can be checked rather than believed.

## Reproducing it

```bash
pip install playwright && playwright install chromium

# any shop, any category page
python -m measure.screen_reader_cost https://example.com/product-category/tea

# several at once, with the raw numbers written out
python -m measure.screen_reader_cost --json measure/shops.example.json --out results.json

# and this shop's side of it
python -m measure.voice_cost
```
