from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EntityType(StrEnum):
    PERSON = "PERSON"
    ADDRESS = "ADDRESS"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    CARD = "CARD"
    IBAN = "IBAN"
    ACCOUNT = "ACCOUNT"
    AADHAAR = "AADHAAR"
    PAN = "PAN"
    UPI = "UPI"
    IFSC = "IFSC"
    IP = "IP"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True, slots=True)
class Entity:
    """A span of text that a detector believes is PII."""

    type: EntityType
    start: int
    end: int
    text: str
    detector: str
    priority: int

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: Entity) -> bool:
        return self.start < other.end and other.start < self.end
