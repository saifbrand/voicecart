"""Working out what somebody is taking back.

Speech repairs itself. A person shopping out loud does not issue clean
commands; they say "no, not that one", "take the last one back", "start
again", and they say it in the middle of the sentence they are already in.
A shop that only understands forward motion makes the shopper carry the
correction themselves - remembering what they added, naming it exactly, and
asking for it to be removed.

So a correction is its own intent, classified here and carried out by the
`repair` tool. Three things people actually say, and nothing invented:

* **take it back** - the last change was wrong, undo it
* **not that one** - the last change was wrong *and* the thing it landed on
  is not what they meant, so it should stop being offered
* **start again** - the whole basket is wrong

Anything else is treated as naming something to take out, which is the
fourth real correction: "no, take the rice out".
"""
from __future__ import annotations

import re
from enum import Enum

# Order matters. "Cancel everything" is a clear-out, not an undo, and
# "not that one" is a rejection rather than a plain undo, so the more
# specific reading is tried first.


class Intent(str, Enum):
    CLEAR = "clear"
    REJECT = "reject"
    UNDO = "undo"
    REMOVE_NAMED = "remove_named"
    UNCLEAR = "unclear"


# The whole basket is wrong.
CLEAR_PHRASES = (
    "start again", "start over", "start from scratch", "from scratch",
    "empty the basket", "empty my basket", "empty it", "clear the basket",
    "clear my basket", "clear it", "forget everything", "forget it all",
    "forget the whole thing", "cancel everything", "cancel the whole",
    "scrap all of it", "scrap it all", "get rid of everything",
)

# The last thing was wrong, and it is not what they meant either.
REJECT_PHRASES = (
    "not that one", "not that", "no not that", "wrong one", "wrong item",
    "that is the wrong", "that was the wrong", "not the one i meant",
    "not what i meant", "not what i said", "i did not mean that",
    "i didn't mean that", "i did not want that", "i didn't want that",
    "a different one", "the other one",
)

# The last thing was wrong. No opinion about what was meant instead.
UNDO_PHRASES = (
    "take that back", "take it back", "take the last one back",
    "take the last back", "the last one back", "put that back",
    "put it back", "undo that", "undo the last", "undo", "cancel that",
    "cancel the last", "go back", "step back", "never mind that",
    "nevermind that", "never mind", "scratch that", "forget that one",
    "forget that",
)


def normalise(said: str) -> str:
    """Compare what was heard, not how it was punctuated.

    Speech arrives transcribed, and a transcriber's apostrophes are its own
    business: "didn't" and "didnt" are the same correction.
    """
    lowered = said.casefold()
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


# The tables are written the way a person says them and compared the way the
# transcript arrives, so they are put through the same wringer once, here.
_CLEAR = tuple(normalise(phrase) for phrase in CLEAR_PHRASES)
_REJECT = tuple(normalise(phrase) for phrase in REJECT_PHRASES)
_UNDO = tuple(normalise(phrase) for phrase in UNDO_PHRASES)


def classify(said: str) -> Intent:
    """What kind of correction this is, if it is one at all."""
    phrase = normalise(said)
    if not phrase:
        return Intent.UNCLEAR

    for intent, phrases in (
        (Intent.CLEAR, _CLEAR),
        (Intent.REJECT, _REJECT),
        (Intent.UNDO, _UNDO),
    ):
        for candidate in phrases:
            if candidate in phrase:
                return intent

    # "No, the rice" and "take the rice out" are corrections too - they just
    # name what they are about.
    if len(phrase.split()) >= 2:
        return Intent.REMOVE_NAMED
    return Intent.UNCLEAR


def strip_correction(said: str) -> str:
    """What is left once the correcting words are taken off the front.

    "no, take the rice out" is about the rice. The shop resolves names, not
    apologies, so the apology goes first.
    """
    phrase = normalise(said)
    leading = (
        "no", "nope", "sorry", "actually", "wait", "hang", "hold", "on",
        "take", "remove", "drop", "delete", "get", "rid", "i", "meant",
        "said", "not", "out", "off", "back", "please", "the", "a", "an",
        "that", "one", "it", "from", "my", "basket", "cart", "of",
    )
    words = phrase.split()
    while words and words[0] in leading:
        words.pop(0)
    while words and words[-1] in leading:
        words.pop()
    return " ".join(words)
