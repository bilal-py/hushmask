"""PII detectors.

Three kinds, in order of trust:
1. Known values: things the user told us about (their own name, address, account numbers). Exact match.
2. Patterns with checksums: cards, IBANs, Aadhaar, and so on. Precise because a random string rarely passes.
3. Patterns without checksums: phones, account numbers next to "A/c". Useful but noisier.

4. A model (GLiNER, optional extra) for names, addresses and places nobody listed. See `ner.py`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from . import validators as v
from .entities import Entity, EntityType

PRIORITY_KNOWN = 100
PRIORITY_CONTEXT = 60  # labelled in the text, e.g. "Account Number: ..."
PRIORITY_CHECKSUM = 50
PRIORITY_FORMAT = 40
PRIORITY_LOOSE = 30
PRIORITY_MODEL = 20


class Detector(Protocol):
    """Finds PII spans.

    Detectors may also set `deterministic = False` (model-based ones do). Only deterministic
    detectors take part in the leak guard, so model noise can't fail a request at random.
    """

    name: str

    def detect(self, text: str) -> list[Entity]: ...


@dataclass(frozen=True)
class PatternDetector:
    name: str
    type: EntityType
    pattern: re.Pattern[str]
    priority: int
    validate: Callable[[str], bool] | None = None
    group: int = 0

    def detect(self, text: str) -> list[Entity]:
        found: list[Entity] = []
        for match in self.pattern.finditer(text):
            value = match.group(self.group)
            if not value or (self.validate and not self.validate(value)):
                continue
            start, end = match.span(self.group)
            found.append(Entity(self.type, start, end, value, self.name, self.priority))
        return found


@dataclass(frozen=True)
class KnownValue:
    """Something the user wants hidden every time, e.g. KnownValue("Rahul Sharma", EntityType.PERSON)."""

    value: str
    type: EntityType = EntityType.CUSTOM

    @classmethod
    def parse(cls, spec: str) -> KnownValue:
        """`"PERSON=Rahul Sharma"` or just `"Rahul Sharma"` (CUSTOM)."""
        head, sep, tail = spec.partition("=")
        if sep and head.strip().upper() in EntityType.__members__:
            return cls(tail.strip(), EntityType[head.strip().upper()])
        return cls(spec.strip())


class KnownValuesDetector:
    """Case-insensitive, whitespace-tolerant exact matches on whole words.

    For PERSON values, each name part of 3+ characters is also matched on its own, so
    "Mr Sharma" doesn't leak when only "Rahul Sharma" was given. Parts get their own tokens.
    """

    name = "known"

    def __init__(self, values: Iterable[KnownValue] = (), *, split_names: bool = True) -> None:
        self._types: dict[str, EntityType] = {}
        for known in values:
            value = " ".join(known.value.split())
            if not value:
                continue
            self._types.setdefault(value.casefold(), known.type)
            if split_names and known.type is EntityType.PERSON:
                for part in value.split():
                    if len(part) >= 3:
                        self._types.setdefault(part.casefold(), known.type)

        self._pattern: re.Pattern[str] | None = None
        if self._types:
            alternatives = sorted(self._types, key=len, reverse=True)
            body = "|".join(re.escape(a).replace(r"\ ", r"\s+") for a in alternatives)
            self._pattern = re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.IGNORECASE)

    @property
    def values(self) -> list[str]:
        return list(self._types)

    def detect(self, text: str) -> list[Entity]:
        if self._pattern is None:
            return []
        found = []
        for match in self._pattern.finditer(text):
            key = " ".join(match.group().split()).casefold()
            found.append(Entity(self._types[key], match.start(), match.end(), match.group(), self.name, PRIORITY_KNOWN))
        return found


def default_detectors() -> list[Detector]:
    return [
        PatternDetector(
            "email",
            EntityType.EMAIL,
            # \w, not A-Z: the evaluation found "anna.müller@web.de" and "grégori…@tutanota.com" leaking.
            re.compile(r"(?<![\w.+-])[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,}(?![\w-])"),
            PRIORITY_FORMAT,
        ),
        # UPI handles look like emails without a dot after the @: name@okhdfcbank
        PatternDetector(
            "upi",
            EntityType.UPI,
            re.compile(r"(?<![\w.+-])[A-Za-z0-9._-]{2,}@[A-Za-z]{2,}(?![\w@-])(?!\.[A-Za-z0-9])"),
            PRIORITY_FORMAT,
        ),
        PatternDetector(
            "card",
            EntityType.CARD,
            re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"),
            PRIORITY_CHECKSUM,
            v.luhn,
        ),
        PatternDetector(
            "iban",
            EntityType.IBAN,
            re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"),
            PRIORITY_CHECKSUM,
            v.iban,
        ),
        PatternDetector(
            "aadhaar",
            EntityType.AADHAAR,
            re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)"),
            PRIORITY_CHECKSUM,
            v.aadhaar,
        ),
        # PAN: 4th letter is the holder type (P = person, C = company, ...)
        PatternDetector(
            "pan",
            EntityType.PAN,
            re.compile(r"\b[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]\b"),
            PRIORITY_FORMAT,
        ),
        PatternDetector(
            "ifsc",
            EntityType.IFSC,
            re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
            PRIORITY_FORMAT,
        ),
        PatternDetector(
            "account",
            EntityType.ACCOUNT,
            re.compile(
                r"(?i)\b(?:a/c|acct|account)(?:\s*(?:no\.?|number|num|#))?\s*[:.#-]?\s*([X*\d][\dX* -]{4,22}\d)"
            ),
            PRIORITY_CONTEXT,
            group=1,
        ),
        PatternDetector(
            "ipv4",
            EntityType.IP,
            re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
            PRIORITY_FORMAT,
            v.ipv4,
        ),
        PatternDetector(
            "phone-intl",
            EntityType.PHONE,
            # Brackets only as a pair around a group, "+44 (20) 7946 0958", so a ")" after the number stays put.
            re.compile(r"(?<![\w+])\+\d{1,3}(?:[ .-]?(?:\(\d{1,5}\)|\d{1,5})){2,5}(?!\d)"),
            PRIORITY_LOOSE,
            v.digit_count(8, 15),
        ),
        PatternDetector(
            "phone-in-mobile",
            EntityType.PHONE,
            re.compile(r"(?<![\d+])0?[6-9]\d{4}[ -]?\d{5}(?!\d)"),
            PRIORITY_LOOSE,
        ),
        # National numbers with a trunk 0 and separators: 020 7946 0958, 030-1234-5678
        PatternDetector(
            "phone-national",
            EntityType.PHONE,
            re.compile(r"(?<![\d+])0\d{2,4}[ -]\d{3,4}[ -]?\d{3,4}(?!\d)"),
            PRIORITY_LOOSE,
            v.digit_count(10, 11),
        ),
        # Other national formats seen in the evaluation: "(776) 5008567", "0296 69224164", "0044 92003-6685",
        # "0167 29.907.3017". Must start with a trunk 0 or a bracketed area code; dates are rejected.
        PatternDetector(
            "phone-national-loose",
            EntityType.PHONE,
            re.compile(r"(?<![\w+.(])(?:\(\d{2,5}\)[ .-]?|0\d{1,4}[ .-]?)(?:\d{1,5}[ .-]?){1,4}\d{2,6}(?!\w)(?!\.\d)"),
            PRIORITY_LOOSE,
            v.all_of(v.digit_count(9, 14), v.not_date_like),
        ),
    ]
