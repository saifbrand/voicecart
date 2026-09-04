"""Working out which product somebody meant.

The rule under all of these: never guess. Adding the wrong thing to the
basket of somebody who cannot see it is worse than asking again.
"""
from __future__ import annotations

import pytest

from voicecart import refer


@pytest.fixture(autouse=True)
def clean_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(refer, "RECENT_FILE", tmp_path / "recent.json")


def heard(*skus: str) -> None:
    refer.remember("tester", list(skus))


def meant(phrase: str) -> refer.Resolution:
    return refer.resolve(phrase, "tester")


def test_a_sku_always_resolves():
    assert meant("TEA-001").sku == "TEA-001"
    assert meant("tea-001").sku == "TEA-001"


def test_a_position_points_into_what_was_just_read():
    heard("TEA-001", "RIC-002", "HON-003")
    assert meant("the second one").sku == "RIC-002"
    assert meant("first").sku == "TEA-001"
    assert meant("the last one").sku == "HON-003"


def test_a_position_past_the_end_says_how_many_there_were():
    heard("TEA-001", "RIC-002")
    outcome = meant("fifth")
    assert not outcome.found
    assert "2 items" in outcome.reason


def test_a_position_with_nothing_read_out_says_so():
    assert "not read anything" in meant("second").reason


def test_a_name_resolves_without_a_list():
    assert meant("bamboo pen").sku == "PEN-012"


def test_the_recent_list_wins_over_the_rest_of_the_shop():
    """Two products say cotton. After hearing one, "cotton" means that one."""
    assert not meant("cotton").found          # ambiguous across the whole shop
    heard("KUR-009")
    assert meant("cotton").sku == "KUR-009"   # unambiguous in what was read


def test_an_ambiguous_name_asks_instead_of_guessing():
    outcome = meant("cotton")
    assert not outcome.found
    assert "Which one" in outcome.reason
    assert len(outcome.candidates) == 2


def test_pointing_works_when_only_one_thing_was_read():
    heard("HON-003")
    assert meant("that one").sku == "HON-003"
    assert meant("it").sku == "HON-003"


def test_pointing_at_a_list_of_three_asks_which():
    heard("TEA-001", "RIC-002", "HON-003")
    outcome = meant("that one")
    assert not outcome.found
    assert "Do you mean" in outcome.reason


def test_a_name_that_starts_with_a_number_word_is_still_a_name():
    """"second" alone is a position. "two towels" is not."""
    heard("TEA-001", "RIC-002", "HON-003")
    assert meant("second").sku == "RIC-002"
    assert meant("cotton hand towel").sku == "TOW-006"


def test_nothing_said_is_not_a_guess():
    assert not meant("   ").found
