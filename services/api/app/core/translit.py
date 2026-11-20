"""Uzbek Cyrillic -> Latin transliteration (rules of the 1995 Latin alphabet).

Uses the ASCII apostrophe for o' / g' / tutuq belgisi so that generated text matches the rule
engine's patterns (scan text is normalised the same way). Text in other scripts is left untouched.
"""

from __future__ import annotations

_VOWELS = set("аеёиоуэюяўАЕЁИОУЭЮЯЎ")
_SIMPLE = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "x",
    "ч": "ch",
    "ш": "sh",
    "щ": "sh",
    "ъ": "'",
    "ь": "",
    "ы": "i",
    "э": "e",
    "ё": "yo",
    "ю": "yu",
    "я": "ya",
    "ў": "o'",
    "қ": "q",
    "ғ": "g'",
    "ҳ": "h",
}


def _is_cyr_letter(ch: str) -> bool:
    return ch.lower() in _SIMPLE or ch.lower() in ("е", "ц")


def cyr_to_lat(text: str) -> str:
    out: list[str] = []
    n = len(text)
    for i, ch in enumerate(text):
        low = ch.lower()
        prev = text[i - 1] if i > 0 else ""
        nxt = text[i + 1] if i + 1 < n else ""
        if low == "е":
            word_start = not prev or not _is_cyr_letter(prev)
            lat = "ye" if word_start or prev in _VOWELS or prev.lower() in ("ъ", "ь") else "e"
        elif low == "ц":
            word_start = not prev or not _is_cyr_letter(prev)
            lat = "s" if word_start or prev not in _VOWELS else "ts"
        elif low in _SIMPLE:
            lat = _SIMPLE[low]
        else:
            out.append(ch)
            continue
        if ch != low and lat:
            # ALL-CAPS word ("НАМУНАВИЙ") -> "NAMUNAVIY"; Title case ("Шартнома") -> "Shartnoma"
            caps_word = (nxt.isupper() and _is_cyr_letter(nxt)) or (prev.isupper() and _is_cyr_letter(prev))
            lat = lat.upper() if caps_word else lat[0].upper() + lat[1:]
        out.append(lat)
    return "".join(out)


def has_cyrillic(text: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in text)
