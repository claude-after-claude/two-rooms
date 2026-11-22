import pytest

from tworooms.words import REFUSED_BASE, Refused, check_message, check_numbers, count_words

ACCEPTED = [
    "A red block about a third of the way across, touching the bottom.",
    "four fifths of the way up",
    "Four-fifths of the way up",
    "seven tenths across, nine tenths up",
    "five sixths, six sevenths, eight ninths",
    "two blue squares, one green, three yellow",
    "half, halves, thirds, quarters, fourths, fifths, sixths, sevenths, eighths, ninths, tenths",
    "the first, the second and the third one; once, twice, double, triple",
    "a tenth of the side, often seen, eighth note, Tenths",
    "it is fourth from the left",
    "attention, intent, often, kitten, weightless",
]

REFUSED_SENTENCES = [
    "the red one is 3 units wide",
    "about 40% across",
    "½ of the way",
    "four of them",
    "five squares",
    "it is six wide",
    "near the corner, seven",
    "four and a half",
    "nine units up",
    "a dozen cells",
    "tens of cells",
    "fours and fives",
    "about a twentieth of the side",
    "twenty-one",
    "one hundredth",
    "the eleventh cell",
    "zeroes",
]


@pytest.mark.parametrize("text", ACCEPTED)
def test_accepted(text):
    check_numbers(text)


@pytest.mark.parametrize("text", REFUSED_SENTENCES)
def test_refused(text):
    with pytest.raises(Refused):
        check_numbers(text)


@pytest.mark.parametrize("word", REFUSED_BASE)
def test_every_refused_word(word):
    plural = word[:-1] + "ies" if word.endswith("y") else word + "s"
    for text in (f"move it {word} more", f"{word.capitalize()} of them", f"about {plural}"):
        with pytest.raises(Refused):
            check_numbers(text)


@pytest.mark.parametrize("word", ["four", "five", "six", "seven", "eight", "nine"])
def test_small_counts_only_before_fractions(word):
    check_numbers(f"{word} tenths")
    with pytest.raises(Refused):
        check_numbers(f"{word} blocks")
    with pytest.raises(Refused):
        check_numbers(f"it ends at {word}")


def test_refusal_explains_and_spends_nothing():
    with pytest.raises(Refused) as e:
        check_message("twelve cells", budget_left=10)
    msg = str(e.value)
    assert "proportion" in msg and "Nothing was spent" in msg


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
