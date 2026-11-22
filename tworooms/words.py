"""Word counting and the no-numbers rule."""
import re

from .config import MAX_MESSAGE_CHARS, MAX_TOKEN_CHARS

FRACTION_WORDS = {
    "half", "halves", "third", "thirds", "quarter", "quarters", "fourth", "fourths", "fifth", "fifths",
    "sixth", "sixths", "seventh", "sevenths", "eighth", "eighths", "ninth", "ninths", "tenth", "tenths",
}
ALWAYS_ALLOWED = {"one", "two", "three", "first", "second", "once", "twice", "double", "triple"} | FRACTION_WORDS
BEFORE_FRACTION_ONLY = ["four", "five", "six", "seven", "eight", "nine"]
_EXAMPLE_FRACTION = {"four": "fifths", "five": "sixths", "six": "sevenths", "seven": "eighths", "eight": "ninths", "nine": "tenths"}

_TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_BIG = ["hundred", "thousand", "million", "dozen", "percent"]
_ORDINALS = [
    "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
    "nineteenth", "twentieth", "thirtieth", "fortieth", "fiftieth", "sixtieth", "seventieth", "eightieth",
    "ninetieth", "hundredth", "thousandth", "millionth",
]
REFUSED_BASE = ["zero"] + _TEENS + _TENS + _BIG + _ORDINALS


def _plural(w: str) -> str:
    if w.endswith("y"):
        return w[:-1] + "ies"
    if w.endswith("x"):
        return w + "es"
    return w + "s"


REFUSED = {w: w for w in REFUSED_BASE}
REFUSED.update({_plural(w): w for w in REFUSED_BASE})
REFUSED.update({"zeroes": "zero"})
# "fours", "sixes": a plural of a small number is always a count, never a fraction
REFUSED.update({_plural(w): w for w in BEFORE_FRACTION_ONLY})

ALLOWED_SUMMARY = (
    "one, two, three, first, second, third, once, twice, double, triple, and the fractions half, third, quarter, "
    "fourth, fifth, sixth, seventh, eighth, ninth, tenth (with their plurals); four to nine only directly before a "
    'fraction word ("four fifths", "seven tenths")'
)

SHAPE_NOUNS = {"block", "rectangle", "rect", "shape", "circle", "oval", "ellipse", "triangle", "square", "bar", "thing",
               "piece", "colour", "color", "blob"}

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
    """Raise Refused with a plain explanation if the text counts in numbers. `exempt` are callsigns that may be
    written as they are (a callsign such as fable52 contains digits but is not a count)."""
    scan = text
    for name in exempt:
        if name:
            scan = re.sub(re.escape(name), " ", scan, flags=re.IGNORECASE)
    for ch in scan:
        if ch.isdigit() or ch.isnumeric():
            raise Refused(
                f'Not sent: it contains the digit "{ch}". Messages may not contain numbers. {_HOW}'
            )
        if ch in "%‰":
            raise Refused(f'Not sent: it contains "{ch}". Messages may not contain percentages. {_HOW}')
    words = [w.lower() for w in _ALPHA.findall(scan)]
    for i, w in enumerate(words):
        if w in REFUSED:
            raise Refused(f'Not sent: "{w}" is a counting word. {_HOW}')
        if w in BEFORE_FRACTION_ONLY:
            nxt = words[i + 1] if i + 1 < len(words) else None
            if nxt not in FRACTION_WORDS:
                hint = ""
                if nxt and nxt.rstrip("s") in SHAPE_NOUNS:
                    hint = (f' Counting the shapes is refused too: write "{nxt}" or "a few {nxt}"; the builder learns '
                            "how many from your description of each.")
                raise Refused(
                    f'Not sent: "{w}" may only be used directly before a fraction word, as in "{w} '
                    f'{_EXAMPLE_FRACTION[w]}".{hint} {_HOW}'
                )


_HOW = (
    "Describe by proportion and relation instead of counting in units: \"about two fifths of the way up\", "
    "\"as wide as the red one\", \"touching its left side\". Allowed: " + ALLOWED_SUMMARY + ". "
    "Nothing was spent from your word budget."
)


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
