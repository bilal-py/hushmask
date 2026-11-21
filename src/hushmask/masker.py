"""Mask PII with tokens, then put the real values back.

A `Masker` is one session (one conversation, one document). Its vault grows as you mask more
text, and the same value always gets the same token, e.g. `PERSON_3f9a1c`. Tokens come from an
HMAC of the normalized value, so pass a fixed `secret` if tokens must stay stable across sessions.
The vault lives in memory only.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from . import validators as v
from .detectors import Detector, KnownValue, KnownValuesDetector, default_detectors
from .entities import Entity, EntityType
from .policy import Policy

_TOKEN = re.compile(r"\b([A-Za-z]+)_([0-9A-Fa-f]{6,64})\b")
_NUMERIC = {EntityType.CARD, EntityType.AADHAAR, EntityType.ACCOUNT, EntityType.IBAN}
# Types whose raw value must never appear anywhere in the output, even inside another word.
_SUBSTRING_GUARDED = frozenset(EntityType) - {EntityType.PERSON, EntityType.ADDRESS, EntityType.CUSTOM}


class LeakError(Exception):
    """Masked text still contains PII. The text must not be sent. The message never includes values."""


@dataclass(frozen=True)
class MaskResult:
    text: str
    entities: tuple[Entity, ...]
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class RestoreResult:
    text: str
    restored: frozenset[str]
    unknown: frozenset[str]
    """Strings that look like our tokens but aren't in the vault (the model may have invented or altered them)."""


def normalize(entity_type: EntityType, value: str) -> str:
    if entity_type is EntityType.PHONE:
        number = v.digits(value)
        return number[-10:] if len(number) >= 10 else number
    if entity_type in _NUMERIC:
        return re.sub(r"[^0-9A-Za-z]", "", value).upper()
    return " ".join(value.split()).casefold()


class Masker:
    def __init__(
        self,
        *,
        policy: Policy | None = None,
        known: Iterable[KnownValue] = (),
        secret: bytes | None = None,
        detectors: Iterable[Detector] | None = None,
    ) -> None:
        self.policy = policy or Policy.strict()
        self._secret = secret or secrets.token_bytes(32)
        self._known = KnownValuesDetector(known)
        self._detectors: list[Detector] = [
            self._known,
            *(default_detectors() if detectors is None else detectors),
        ]
        self._vault: dict[str, str] = {}
        self._token_of: dict[tuple[EntityType, str], str] = {}

    @property
    def vault(self) -> Mapping[str, str]:
        """token -> original value (first form seen). Treat as sensitive."""
        return MappingProxyType(self._vault)

    def load_vault(self, vault: Mapping[str, str]) -> None:
        """Restore-only session from a saved vault (e.g. the CLI). Masking new text will not reuse these tokens."""
        self._vault.update(vault)

    def detect(self, text: str) -> list[Entity]:
        candidates = [
            e
            for d in self._detectors
            for e in d.detect(text)
            if e.detector == KnownValuesDetector.name or self.policy.allows(e.type)
        ]
        # Longest first, so a name inside an email masks the whole email; trust breaks ties.
        candidates.sort(key=lambda e: (-e.length, -e.priority, e.start))
        chosen: list[Entity] = []
        for entity in candidates:
            if not any(entity.overlaps(c) for c in chosen):
                chosen.append(entity)
        return sorted(chosen, key=lambda e: e.start)

    def mask(self, text: str) -> MaskResult:
        entities = self.detect(text)
        parts: list[str] = []
        tokens: list[str] = []
        pos = 0
        for entity in entities:
            token = self._token_for(entity)
            parts += (text[pos : entity.start], token)
            tokens.append(token)
            pos = entity.end
        parts.append(text[pos:])
        masked = "".join(parts)
        self._guard(masked)
        return MaskResult(masked, tuple(entities), tuple(tokens))

    def restore(self, text: str) -> RestoreResult:
        restored: set[str] = set()
        unknown: set[str] = set()
        out = self._restore_str(text, restored, unknown)
        return RestoreResult(out, frozenset(restored), frozenset(unknown))

    def restore_json(self, value: Any) -> tuple[Any, RestoreResult]:
        """Restore every string (keys included) inside parsed JSON, e.g. a structured-output response."""
        restored: set[str] = set()
        unknown: set[str] = set()

        def walk(node: Any) -> Any:
            if isinstance(node, str):
                return self._restore_str(node, restored, unknown)
            if isinstance(node, list):
                return [walk(item) for item in node]
            if isinstance(node, dict):
                return {walk(k): walk(item) for k, item in node.items()}
            return node

        result = walk(value)
        return result, RestoreResult("", frozenset(restored), frozenset(unknown))

    # -- internals ---------------------------------------------------------------------------

    def _token_for(self, entity: Entity) -> str:
        key = (entity.type, normalize(entity.type, entity.text))
        if token := self._token_of.get(key):
            return token
        digest = hmac.new(self._secret, f"{key[0]}:{key[1]}".encode(), hashlib.sha256).hexdigest()
        length = 6
        token = f"{entity.type}_{digest[:length]}"
        while token in self._vault:  # different value, same short hash: lengthen
            length += 2
            token = f"{entity.type}_{digest[:length]}"
        self._token_of[key] = token
        self._vault[token] = entity.text
        return token

    def _restore_str(self, text: str, restored: set[str], unknown: set[str]) -> str:
        def replace(match: re.Match[str]) -> str:
            kind, digest = match.group(1).upper(), match.group(2).lower()
            token = f"{kind}_{digest}"
            if token in self._vault:
                restored.add(token)
                return self._vault[token]
            if kind in EntityType.__members__:
                unknown.add(match.group())
            return match.group()

        return _TOKEN.sub(replace, text)

    def _guard(self, masked: str) -> None:
        """Last check before text leaves: fail closed if any PII is still visible."""
        leaked: set[str] = set()
        token_spans = [m.span() for m in _TOKEN.finditer(masked)]
        for d in self._detectors:
            for e in d.detect(masked):
                inside_token = any(s <= e.start and e.end <= t for s, t in token_spans)
                if not inside_token and (e.detector == KnownValuesDetector.name or self.policy.allows(e.type)):
                    leaked.add(e.type)
        folded = masked.casefold()
        for token, original in self._vault.items():
            kind = EntityType(token.rsplit("_", 1)[0])
            if kind in _SUBSTRING_GUARDED and original.casefold() in folded:
                leaked.add(kind)
        if leaked:
            raise LeakError(f"PII still visible after masking ({', '.join(sorted(leaked))}); refusing to release text")
