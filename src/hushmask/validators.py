"""Checksum and format validators. Each takes the matched text and returns True if it is plausible."""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")


def digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def luhn(value: str) -> bool:
    """Payment cards. 13-19 digits with a valid Luhn checksum."""
    number = digits(value)
    if not 13 <= len(number) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(number)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def iban(value: str) -> bool:
    """ISO 13616: move the first four characters to the end, letters to numbers, mod 97 == 1."""
    compact = _NON_ALNUM.sub("", value).upper()
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(numeric) % 97 == 1


_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff(value: str) -> bool:
    number = digits(value)
    if not number:
        return False
    check = 0
    for i, ch in enumerate(reversed(number)):
        check = _VERHOEFF_D[check][_VERHOEFF_P[i % 8][int(ch)]]
    return check == 0


def aadhaar(value: str) -> bool:
    """Indian Aadhaar: 12 digits, never starts with 0 or 1, Verhoeff checksum."""
    number = digits(value)
    return len(number) == 12 and number[0] not in "01" and verhoeff(number)


def digit_count(low: int, high: int):
    def check(value: str) -> bool:
        return low <= len(digits(value)) <= high

    return check


_DATE = re.compile(r"(?<!\d)\d{1,4}[./-]\d{1,2}[./-]\d{1,4}(?!\d)")


def not_date_like(value: str) -> bool:
    """Reject "01.02.2026 1030"-style runs: dates must stay readable on statements."""
    return _DATE.search(value) is None


def all_of(*checks):
    def check(value: str) -> bool:
        return all(c(value) for c in checks)

    return check


def ipv4(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) <= 255 and str(int(p)) == p for p in parts)
