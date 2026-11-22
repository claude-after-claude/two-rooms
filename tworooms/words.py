"""Word counting and the no-numbers rule."""
import re

from .config import MAX_MESSAGE_CHARS, MAX_TOKEN_CHARS

RULE = ("You may count things up to nine (three windows, two legs) and cut things in halves, thirds and quarters; "
        "nothing finer, no digits, and no counting in fractions (five quarters).")

NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
FRACTIONS = {"half": 2, "halves": 2, "third": 3, "thirds": 3, "quarter": 4, "quarters": 4}
ALLOWED_WORDS = list(NUMBERS) + ["first", "second", "third", "once", "twice", "double", "triple",
                                  "half", "halves", "thirds", "quarter", "quarters"]

_ABOVE_NINE = (["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
                "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
                "thousand", "million", "dozen", "percent"])
_FINER = ["fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth", "thirteenth",
          "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twentieth", "thirtieth",
          "fortieth", "fiftieth", "sixtieth", "seventieth", "eightieth", "ninetieth", "hundredth", "thousandth",
          "millionth"]
REFUSED_BASE = _ABOVE_NINE + _FINER


def _plural(w: str) -> str:
    if w.endswith("y"):
        return w[:-1] + "ies"
    return w + "s"


REFUSED = {}
for _w in _ABOVE_NINE:
    REFUSED[_w] = REFUSED[_plural(_w)] = "above"
for _w in _FINER:
    REFUSED[_w] = REFUSED[_plural(_w)] = "finer"

_ALPHA = re.compile(r"[^\W\d_]+")
_SPLIT = re.compile(r"[-/_]")


def count_words(text: str) -> tuple[int, list[str]]:
    """Split on whitespace, then on - / _. Pieces with no letter or digit (a lone dash, an ellipsis) don't count."""
    pieces = []
    for tok in text.split():
        for p in _SPLIT.split(tok):
            if any(ch.isalnum() for ch in p):
                pieces.append(p)
    return len(pieces), pieces


class Refused(ValueError):
    pass


def check_numbers(text: str, exempt: tuple[str, ...] = ()) -> None:
    """Raise Refused with a plain explanation if the text breaks the number rule. `exempt` are callsigns that may be
    written as they are (a callsign such as fable52 contains digits but is not a count)."""
    scan = text
    for name in exempt:
        if name:
            scan = re.sub(re.escape(name), " ", scan, flags=re.IGNORECASE)
    for ch in scan:
        if ch.isdigit() or ch.isnumeric():
            raise Refused(f'Not sent: it contains the digit "{ch}"; write numbers as words, up to nine. {_HOW}')
        if ch in "%‰":
            raise Refused(f'Not sent: it contains "{ch}". {_HOW}')
    words = [w.lower() for w in _ALPHA.findall(scan)]
    for i, w in enumerate(words):
        kind = REFUSED.get(w)
        if kind == "above":
            raise Refused(f'Not sent: "{w}" counts past nine. {_HOW}')
        if kind == "finer":
            raise Refused(f'Not sent: "{w}" cuts finer than a quarter. {_HOW}')
        if w in FRACTIONS and i > 0 and words[i - 1] in NUMBERS and NUMBERS[words[i - 1]] >= FRACTIONS[w]:
            raise Refused(
                f'Not sent: "{words[i - 1]} {w}" counts in {w if w.endswith("s") else w + "s"}, and counting in '
                "fractions is counting. The number in front of a fraction must be smaller than its bottom: "
                f'"three quarters", "two thirds", "one half". {_HOW}')


_HOW = (RULE + ' Describe by proportion and relation: "about a third of the way up", "as wide as the red one", '
        '"touching its left side". Nothing was spent from your word budget.')


def check_message(text: str, budget_left: int | None = None, exempt: tuple[str, ...] = (), unit: str = "round") -> int:
    """Validate a message from a player. Returns its word count. Raises Refused."""
    if not isinstance(text, str) or not text.strip():
        raise Refused("Not sent: the message is empty.")
    if len(text) > MAX_MESSAGE_CHARS:
        raise Refused(f"Not sent: a message is at most {MAX_MESSAGE_CHARS:,} characters; this one has {len(text):,}.")
    n, pieces = count_words(text)
    for p in pieces:
        if len(p) > MAX_TOKEN_CHARS:
            raise Refused(
                f'Not sent: "{p[:40]}…" is longer than {MAX_TOKEN_CHARS} characters; no word may be that long. '
                "Nothing was spent from your word budget."
            )
    check_numbers(text, exempt)
    if budget_left is not None and n > budget_left:
        raise Refused(
            f"Not sent: it is {n} words and you have {budget_left} left for this {unit}. "
            "Shorten it; nothing was spent."
        )
    return n
