"""PII masking before any text leaves our infrastructure (spec §10).

Masks: PINFL (14 digits), passport (AA1234567), phone numbers, emails, bank
accounts (20 digits), card numbers, STIR (9 digits) and capitalised
full names following typical Uzbek/Russian patterns (…ovich/…ovna/…ov).
Masking is reversible only via the returned mapping, kept in memory.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("ACCOUNT", re.compile(r"\b\d{20}\b")),
    ("CARD", re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")),
    ("PINFL", re.compile(r"\b[3-6]\d{13}\b")),
    ("PHONE", re.compile(r"(?:\+?998[\s-]?)?\(?\d{2}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b")),
    ("PASSPORT", re.compile(r"\b[A-Z]{2}\s?\d{7}\b")),
    ("STIR", re.compile(r"\b[2-7]\d{8}\b")),
    (
        "NAME",
        re.compile(
            r"\b[A-ZА-ЯЎҚҒҲ][a-zа-яўқғҳ'ʻ]+\s+[A-ZА-ЯЎҚҒҲ][a-zа-яўқғҳ'ʻ]+\s+"
            r"[A-ZА-ЯЎҚҒҲ][a-zа-яўқғҳ'ʻ]+(?:ovich|evich|ovna|evna|o'g'li|qizi|ович|евич|овна|евна|ўғли|қизи)\b"
        ),
    ),
]


def mask(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}

    def repl(kind: str):  # type: ignore[no-untyped-def]
        def _r(m: re.Match[str]) -> str:
            value = m.group(0)
            for k, v in mapping.items():
                if v == value:
                    return k
            counters[kind] = counters.get(kind, 0) + 1
            token = f"[{kind}_{counters[kind]}]"
            mapping[token] = value
            return token

        return _r

    for kind, rx in _PATTERNS:
        text = rx.sub(repl(kind), text)
    return text, mapping


def unmask(text: str, mapping: dict[str, str]) -> str:
    for token, value in mapping.items():
        text = text.replace(token, value)
    return text
