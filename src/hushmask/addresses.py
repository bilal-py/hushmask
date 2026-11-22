"""Street addresses by pattern: German/Dutch, US/UK/Australian, and French/Italian/Spanish styles.

These are deliberately conservative. A street needs a street word ("straße", "Street", "rue", "Via"…) and a
house number; ambiguous German suffixes ("ring", "weg") also need a postcode and city, so "Spring 2026" or
"Monitoring 2" never match. House numbers can't be part of an amount ("10.99"), "Dr" isn't a street suffix
(statements use it for debit), and Romance keywords must be capitalized ("Via Roma 10", not "via PayPal 10").
The names model still catches the free-form rest.
"""

from __future__ import annotations

import re

from .detectors import PRIORITY_FORMAT
from .entities import Entity, EntityType

_U = "A-ZÄÖÜÀ-ÖØ-Þ"  # upper-case letters, incl. accented
_WORD = rf"[{_U}][\w'\u2019.-]*"
_HOUSE = r"\d{1,4}\s?[a-zA-Z]?(?:\s?[-/]\s?\d{1,4}[a-zA-Z]?)?(?![.,]\d)(?!\w)"
_CITY = rf"[{_U}][\w'\u2019-]+(?:[ -][{_U}][\w'\u2019-]+){{0,2}}"

# German / Dutch / Austrian / Swiss: "Bergstraße 12", "Lange Straße 5a", "Keizersgracht 123, 1015 CJ Amsterdam"
_SAFE = ("straße", "strasse", "str.", "allee", "gasse", "platz", "damm", "chaussee", "gracht", "straat", "laan",
         "plein", "kade", "steeg", "promenade")  # fmt: skip
_AMBIGUOUS = ("weg", "ring", "ufer", "steig", "pfad", "dijk", "markt", "berg", "hof")
_STANDALONE = {"straße", "strasse", "str.", "allee", "gasse", "platz", "weg", "ring", "markt", "damm", "ufer"}
_ADJECTIVES = {"alte", "alter", "altes", "neue", "neuer", "neues", "lange", "langer", "große", "großer", "kleine",
               "kleiner", "hohe", "hoher", "obere", "untere", "am", "an", "auf", "im", "in", "zum", "zur"}  # fmt: skip
_DE = re.compile(
    rf"(?<![\w])(?P<street>(?:{_WORD}\s+){{0,2}}{_WORD})\s+(?P<house>{_HOUSE})"
    rf"(?P<post>,?\s+\d{{4,5}}(?:\s?[A-Z]{{2}})?\s+{_CITY})?"
)

# US / UK / Australia: "1600 Pennsylvania Ave NW", "Unit 3/42 Smith St, Sydney NSW 2000", "10 Downing Street"
_EN_SUFFIX = (
    "Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Court|Ct|Way|Place|Pl|Terrace|Tce|Crescent|Cres|"
    "Parade|Pde|Highway|Hwy|Close|Circuit|Cct|Square|Sq|Grove|Gardens|Mews|Row|Walk|Parkway|Pkwy"
)
_EN = re.compile(
    rf"(?<![\w/.,])(?:(?:Unit|Apt|Suite|Flat)\s*\w+\s*[,/]?\s*)?\d{{1,6}}[A-Za-z]?(?:/\d{{1,6}})?"
    rf"\s+(?:{_WORD}\s+){{1,4}}?(?i:{_EN_SUFFIX})\.?(?![\w])"
    r"(?:\s+(?:N|S|E|W|NE|NW|SE|SW)\b)?"
    r"(?:,?\s+(?:Apt|Suite|Unit|Ste|#)\.?\s*[\w-]+)?"
    # locality: "Washington, DC 20500", "Sydney NSW 2000", "London SW1A 2AA", "Pune 411001"
    rf"(?:,\s*(?:{_WORD}\s?){{1,3}},?\s+"
    r"(?:(?:[A-Z]{2,3}\s+)?\d{4,6}(?:-\d{4})?|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}))?"
)

# French: "12 rue de Rivoli, 75001 Paris"
_FR = re.compile(
    r"(?<![\w.,])\d{1,4}(?:\s?(?:bis|ter))?,?\s+"
    r"(?i:rue|avenue|av\.|boulevard|bd|place|chemin|allée|impasse|quai|route|cours)\s+"
    rf"(?:(?:de\s+la|de\s+l'|du|des|de|d')\s*)?{_WORD}(?:\s+{_WORD}){{0,3}}"
    rf"(?:,?\s+\d{{5}}\s+{_CITY})?"
)

# Italian / Spanish / Portuguese / Catalan: "Via Roma 10", "Calle Mayor 5, 28013 Madrid"
_ROMANCE = re.compile(
    r"(?<![\w])(?:Via|Viale|Piazza|Corso|Largo|Calle|Avenida|Avda\.|Plaza|Paseo|Carrer|Rua|Travessa)\s+"
    rf"(?:(?:del|della|delle|dei|de|di|la|los|las|dos|das|do|da)\s+)?{_WORD}(?:\s+{_WORD}){{0,3}},?\s+"
    rf"(?:n\.?\s?)?{_HOUSE}"
    rf"(?:,?\s+\d{{5}}\s+{_CITY})?"
)


def _german_street(street: str, has_post: bool) -> int | None:
    """Return how many leading words to drop, or None if this isn't a street."""
    words = street.split()
    last = words[-1].casefold()
    if last in _STANDALONE:  # "Lange Straße": keep adjectives before it, drop anything else
        if len(words) == 1 and not has_post:
            return None  # a bare "Platz 2" is a ranking, not an address
        keep = 1
        while keep < len(words) and words[-keep - 1].casefold() in _ADJECTIVES | {"der", "den", "dem"}:
            keep += 1
        if keep == 1 and len(words) > 1:
            keep = 2  # "Kurfürsten Straße"
        return len(words) - keep
    if last.endswith(_SAFE) or (has_post and last.endswith(_AMBIGUOUS)):
        return len(words) - 1  # compound: "Bergstraße"; earlier capitalized words are not part of it
    return None


class AddressDetector:
    name = "address"

    def detect(self, text: str) -> list[Entity]:
        found: list[Entity] = []
        for match in _DE.finditer(text):
            drop = _german_street(match.group("street"), bool(match.group("post")))
            if drop is None:
                continue
            start = match.start("street")
            for _ in range(drop):
                start = text.index(" ", start) + 1
                while text[start].isspace():
                    start += 1
            found.append(self._entity(text, start, match.end()))
        for pattern in (_EN, _FR, _ROMANCE):
            for match in pattern.finditer(text):
                found.append(self._entity(text, match.start(), match.end()))
        return found

    def _entity(self, text: str, start: int, end: int) -> Entity:
        return Entity(EntityType.ADDRESS, start, end, text[start:end], self.name, PRIORITY_FORMAT)
