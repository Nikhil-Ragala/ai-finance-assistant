"""Text preprocessing shared by training and the Flask app (keeps the two in sync)."""
import re

_num = re.compile(r"\d+([.,]\d+)?")
_non_alnum = re.compile(r"[^a-z\s]")
_spaces = re.compile(r"\s+")


def clean_text(text) -> str:
    """lower-case, drop numbers/punctuation, collapse whitespace.

    'Swiggy dinner 450!' -> 'swiggy dinner'
    """
    if text is None:
        return ""
    text = str(text).lower()
    text = _num.sub(" ", text)
    text = _non_alnum.sub(" ", text)
    return _spaces.sub(" ", text).strip()
