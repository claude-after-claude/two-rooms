import pytest

from tworooms.words import ALLOWED_WORDS, REFUSED_BASE, Refused, check_message, check_numbers, count_words

ACCEPTED = [
    "A red block about a third of the way across, touching the bottom.",
    "Four blocks along the bottom; six shapes in all.",
    "three windows, two legs, nine spots, five petals",
    "three quarters of the way up, two thirds across, one half",
    "half, halves, thirds, quarters, the first, the second, the third",
    "once, twice, double, triple",
    "a quarter of the way in, a third as wide",
    "the red ones, a zero of a gap",            # zero is not past nine and not a fraction
    "attention, intent, often, kitten, weightless, fiftyish",
    "both halves of it, the other half",
    "half a quarter",                           # compounds are not caught; the transcript is public
]

REFUSED_SENTENCES = [
    ("the red one is 3 units wide", "digit"),
    ("about forty% across", "%"),
    ("½ of the way", "digit"),
    ("ten of them", "past nine"),
    ("twelve cells", "past nine"),
    ("twenty-one", "past nine"),
    ("a dozen cells", "past nine"),
    ("tens of cells", "past nine"),
    ("about a fifth of the way up", "finer"),
    ("seven tenths across", "finer"),
    ("one eighth", "finer"),
    ("it is fourth from the left", "finer"),
    ("the eleventh cell", "finer"),
    ("one hundredth", "finer"),
    ("five quarters of its width", "counting in fractions"),
    ("seven quarters", "counting in fractions"),
    ("four quarters", "counting in fractions"),
    ("five thirds", "counting in fractions"),
    ("three thirds", "counting in fractions"),
    ("two halves", "counting in fractions"),
    ("three halves as tall", "counting in fractions"),
    ("four-quarters", "counting in fractions"),
]


@pytest.mark.parametrize("text", ACCEPTED)
def test_accepted(text):
    check_numbers(text)


@pytest.mark.parametrize("text,why", REFUSED_SENTENCES)
def test_refused(text, why):
    with pytest.raises(Refused) as e:
        check_numbers(text)
    assert why in str(e.value)


@pytest.mark.parametrize("word", REFUSED_BASE)
def test_every_refused_word(word):
    plural = word[:-1] + "ies" if word.endswith("y") else word + "s"
    for text in (f"move it {word} more", f"{word.capitalize()} of them", f"about {plural}"):
        with pytest.raises(Refused):
            check_numbers(text)


@pytest.mark.parametrize("word", ALLOWED_WORDS)
def test_every_allowed_word(word):
    check_numbers(f"about {word} of it")
    check_numbers(f"{word.capitalize()}, then the rest")


def test_numerator_must_be_smaller_than_denominator():
    for ok in ("one half", "one third", "two thirds", "one quarter", "two quarters", "three quarters"):
        check_numbers(ok)
    for bad in ("two halves", "three thirds", "four quarters", "nine quarters", "eight thirds"):
        with pytest.raises(Refused):
            check_numbers(bad)


def test_refusal_explains_the_rule_and_spends_nothing():
    with pytest.raises(Refused) as e:
        check_message("twelve cells", budget_left=10)
    msg = str(e.value)
    assert "count things up to nine" in msg and "halves, thirds and quarters" in msg and "Nothing was spent" in msg


def test_callsigns_with_digits_are_not_numbers():
    check_numbers("thanks fable52, that was close", exempt=("fable52",))
    with pytest.raises(Refused):
        check_numbers("thanks fable52", exempt=())


def test_word_counting():
    assert count_words("a red block")[0] == 3
    assert count_words("red-ish/blue_thing")[0] == 4
    assert count_words("  lots   of\nspace\t")[0] == 3
    assert count_words("wait — what … ok")[0] == 3
    assert count_words("it's the left-most one")[0] == 5
    assert count_words("")[0] == 0


def test_long_tokens_and_budget():
    with pytest.raises(Refused):
        check_message("a" * 25)
    assert check_message("a" * 24) == 1
    assert check_message("one two three", budget_left=3) == 3
    with pytest.raises(Refused):
        check_message("one two three", budget_left=2)
    with pytest.raises(Refused):
        check_message("x " * 1001)
    with pytest.raises(Refused):
        check_message("   ")
