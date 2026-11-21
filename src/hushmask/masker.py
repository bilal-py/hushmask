"""Mask PII with tokens, then put the real values back.

A `Masker` is one session (one conversation, one document). Its vault grows as you mask more
text, and the same value always gets the same token, e.g. `PERSON_3f9a1c`. Tokens come from an
HMAC of the normalized value, so pass a fixed `secret` if tokens must stay stable across sessions.
The vault lives in memory only.

Shorter forms of a known full name are linked to it: if "Rahul Sharma" is `PERSON_3f9a1c`, then
"Mr Sharma" becomes `PERSON_3f9a1c_1` and "R. Sharma" `PERSON_3f9a1c_2`. The AI can see they are
the same person, and each restores to exactly what was written.
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

_TOKEN = re.compile(r"\b([A-Za-z]+)_([0-9A-Fa-f]{6,64}(?:_\d{1,3})?)\b")
_NUMERIC = {EntityType.CARD, EntityType.AADHAAR, EntityType.ACCOUNT, EntityType.IBAN}
# Types whose raw value must never appear anywhere in the output, even inside another word.
_SUBSTRING_GUARDED = frozenset(EntityType) - {
    EntityType.PERSON,
    EntityType.ADDRESS,
    EntityType.LOCATION,
    EntityType.CUSTOM,
}
_NAME_WORD = re.compile(r"[^\W\d_]+")
_TITLES = frozenset({"mr", "mrs", "ms", "miss", "mx", "dr", "prof", "shri", "smt", "sri"})


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


def name_words(value: str) -> tuple[str, ...]:
    return tuple(w for w in _NAME_WORD.findall(value.casefold()) if w not in _TITLES)


def is_name_variant(short: tuple[str, ...], full: tuple[str, ...]) -> bool:
    """True if `short` is a shorter form of `full`: its words appear in order, each either equal or an initial.

    ("sharma",) and ("r", "sharma") are variants of ("rahul", "sharma"); ("rahul", "verma") is not.
    At least one word must match in full, so a lone initial never links.
    """
    if not short or len(short) > len(full) or short == full:
        return False
    i = 0
    whole_match = False
    for word in short:
        while i < len(full) and not (word == full[i] or (len(word) == 1 and full[i].startswith(word))):
            i += 1
        if i == len(full):
            return False
        whole_match |= word == full[i]
        i += 1
    return whole_match


class Masker:
    def __init__(
        self,
        *,
        policy: Policy | None = None,
        known: Iterable[KnownValue] = (),
        secret: bytes | None = None,
        detectors: Iterable[Detector] | None = None,
        extra_detectors: Iterable[Detector] = (),
    ) -> None:
        """`detectors` replaces the built-in pattern detectors; `extra_detectors` adds to them (e.g. GlinerDetector)."""
        known = list(known)
        self.policy = policy or Policy.strict()
        self._secret = secret or secrets.token_bytes(32)
        self._known = KnownValuesDetector(known)
        self._detectors: list[Detector] = [
            self._known,
            *(default_detectors() if detectors is None else detectors),
            *extra_detectors,
        ]
        self._vault: dict[str, str] = {}
        self._token_of: dict[tuple[EntityType, str], str] = {}
        # Full names (2+ words) that shorter mentions can link to: name words -> base token.
        self._full_names: dict[tuple[str, ...], str] = {}
        self._variant_count: dict[str, int] = {}
        # Known full names are link targets even before they appear in any text.
        for k in known:
            if k.type is EntityType.PERSON and len(name_words(k.value)) >= 2:
                self._token_for(Entity(EntityType.PERSON, 0, 0, " ".join(k.value.split()), "known", 0))

    @property
    def vault(self) -> Mapping[str, str]:
        """token -> original value (first form seen). Treat as sensitive."""
        return MappingProxyType(self._vault)

    def load_vault(self, vault: Mapping[str, str]) -> None:
        """Restore-only session from a saved vault (e.g. the CLI). Masking new text will not reuse these tokens."""
        self._vault.update(vault)

    def detect(self, text: str, *, use_models: bool = True) -> list[Entity]:
        """`use_models=False` skips model-based detectors, e.g. for instructions where their noise does harm."""
        candidates = [
            e
            for d in self._detectors
            if use_models or getattr(d, "deterministic", True)
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

    def mask(self, text: str, *, use_models: bool = True) -> MaskResult:
        entities = self.detect(text, use_models=use_models)
        # Full names get their tokens before shorter mentions, so "Mr Sharma" can link to
        # "Rahul Sharma" even when it appears first in the text.
        order = sorted(range(len(entities)), key=lambda i: -len(name_words(entities[i].text)))
        token_at: dict[int, str] = {}
        for i in order:
            token_at[i] = self._token_for(entities[i])

        parts: list[str] = []
        pos = 0
        for i, entity in enumerate(entities):
            parts += (text[pos : entity.start], token_at[i])
            pos = entity.end
        parts.append(text[pos:])
        masked = "".join(parts)
        self._guard(masked)
        return MaskResult(masked, tuple(entities), tuple(token_at[i] for i in range(len(entities))))

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

    # -- tokens ------------------------------------------------------------------------------

    def _token_for(self, entity: Entity) -> str:
        key = (entity.type, normalize(entity.type, entity.text))
        if token := self._token_of.get(key):
            return token
        if entity.type is EntityType.PERSON:
            token = self._person_token(entity.text)
        else:
            token = self._new_token(entity.type, key[1], entity.text)
        self._token_of[key] = token
        return token

    def _new_token(self, entity_type: EntityType, normalized: str, original: str) -> str:
        digest = hmac.new(self._secret, f"{entity_type}:{normalized}".encode(), hashlib.sha256).hexdigest()
        length = 6
        token = f"{entity_type}_{digest[:length]}"
        while token in self._vault:  # different value, same short hash: lengthen
            length += 2
            token = f"{entity_type}_{digest[:length]}"
        self._vault[token] = original
        return token

    def _person_token(self, surface: str) -> str:
        words = name_words(surface)
        if words in self._full_names:  # same name, written differently ("Mr Rahul Sharma")
            return self._new_variant(self._full_names[words], surface)
        bases = {base for full, base in self._full_names.items() if is_name_variant(words, full)}
        if len(bases) == 1:  # two different Sharmas: ambiguous, don't guess
            return self._new_variant(bases.pop(), surface)
        token = self._new_token(EntityType.PERSON, normalize(EntityType.PERSON, surface), surface)
        if len(words) >= 2:
            self._full_names.setdefault(words, token)
        return token

    def _new_variant(self, base: str, surface: str) -> str:
        n = self._variant_count.get(base, 0) + 1
        self._variant_count[base] = n
        token = f"{base}_{n}"
        self._vault[token] = surface
        return token

    # -- restore and guard -------------------------------------------------------------------

    def _restore_str(self, text: str, restored: set[str], unknown: set[str]) -> str:
        def replace(match: re.Match[str]) -> str:
            kind, rest = match.group(1).upper(), match.group(2).lower()
            token = f"{kind}_{rest}"
            if token in self._vault:
                restored.add(token)
                return self._vault[token]
            if kind in EntityType.__members__:
                unknown.add(match.group())
            return match.group()

        return _TOKEN.sub(replace, text)

    def _guard(self, masked: str) -> None:
        """Last check before text leaves: fail closed if any PII is still visible.

        Only deterministic detectors run here. A model can flag something new just because the
        surrounding text changed, and that must not fail requests at random.
        """
        leaked: set[str] = set()
        token_spans = [m.span() for m in _TOKEN.finditer(masked)]
        for d in self._detectors:
            if not getattr(d, "deterministic", True):
                continue
            for e in d.detect(masked):
                inside_token = any(s <= e.start and e.end <= t for s, t in token_spans)
                if not inside_token and (e.detector == KnownValuesDetector.name or self.policy.allows(e.type)):
                    leaked.add(e.type)
        folded = masked.casefold()
        for token, original in self._vault.items():
            kind = EntityType(token.split("_", 1)[0])
            if kind in _SUBSTRING_GUARDED and original.casefold() in folded:
                leaked.add(kind)
        if leaked:
            raise LeakError(f"PII still visible after masking ({', '.join(sorted(leaked))}); refusing to release text")
