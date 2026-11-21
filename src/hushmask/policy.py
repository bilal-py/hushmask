from __future__ import annotations

from dataclasses import dataclass

from .entities import EntityType

_ALL = frozenset(EntityType)

PRESETS: dict[str, frozenset[EntityType]] = {
    "strict": _ALL,
    # Branch codes, IPs and cities say little about a person, and cities often sit inside merchant
    # names ("MCDONALDS KORAMANGALA") that the AI needs to categorize.
    "finance": _ALL - {EntityType.IFSC, EntityType.IP, EntityType.LOCATION},
}


@dataclass(frozen=True)
class Policy:
    """Which entity types get masked. Values the user listed as known are always masked."""

    enabled: frozenset[EntityType]
    name: str = "custom"

    @classmethod
    def preset(cls, name: str) -> Policy:
        try:
            return cls(PRESETS[name], name)
        except KeyError:
            raise ValueError(f"Unknown preset {name!r}. Choose from: {', '.join(PRESETS)}") from None

    @classmethod
    def strict(cls) -> Policy:
        return cls.preset("strict")

    def allows(self, entity_type: EntityType) -> bool:
        return entity_type in self.enabled
