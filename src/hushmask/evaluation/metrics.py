"""Scoring masking against labelled data.

What matters for privacy is whether the characters of a real value were hidden, not whether we guessed its
type. So a gold value is:

* **protected** when every character is inside some masked span,
* **partly visible** when some characters are masked and some aren't (counted as a leak: part of a card
  number or a surname is still out),
* **leaked** when nothing of it was masked.

Over-masking is a masked span that touches no labelled value at all, plus labelled "keep" spans (merchants)
that got damaged, because those are what the AI needs to do its job.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..entities import Entity


@dataclass(frozen=True)
class Span:
    label: str  # an EntityType value, or an out-of-scope label such as "USERNAME"
    start: int
    end: int


@dataclass
class Doc:
    text: str
    gold: list[Span]
    keep: list[Span] = field(default_factory=list)  # must stay readable, e.g. merchants
    known: list[Any] = field(default_factory=list)  # KnownValue list a real user would give
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Score:
    total: Counter[str] = field(default_factory=Counter)
    protected: Counter[str] = field(default_factory=Counter)
    partial: Counter[str] = field(default_factory=Counter)
    leaked: Counter[str] = field(default_factory=Counter)
    out_of_scope: Counter[str] = field(default_factory=Counter)
    out_of_scope_protected: Counter[str] = field(default_factory=Counter)
    false_positives: int = 0
    false_positive_examples: list[str] = field(default_factory=list)
    keep_total: int = 0
    keep_damaged: int = 0
    keep_damaged_examples: list[str] = field(default_factory=list)
    docs: int = 0
    seconds: float = 0.0

    def add(self, doc: Doc, predicted: list[Entity], in_scope: set[str]) -> None:
        self.docs += 1
        covered = _coverage(len(doc.text), predicted)
        for span in doc.gold:
            # Whitespace inside a value ("Anna Weber") isn't private; only the other characters count.
            positions = [i for i in range(span.start, span.end) if not doc.text[i].isspace()]
            hidden = sum(covered[i] for i in positions)
            length = len(positions)
            if span.label not in in_scope:
                self.out_of_scope[span.label] += 1
                if hidden == length:
                    self.out_of_scope_protected[span.label] += 1
                continue
            self.total[span.label] += 1
            if hidden == length:
                self.protected[span.label] += 1
            elif hidden:
                self.partial[span.label] += 1
            else:
                self.leaked[span.label] += 1
        for entity in predicted:
            if not any(entity.start < g.end and g.start < entity.end for g in doc.gold):
                self.false_positives += 1
                if len(self.false_positive_examples) < 12:
                    self.false_positive_examples.append(f"{entity.type}: {entity.text!r}")
        for span in doc.keep:
            self.keep_total += 1
            if any(covered[span.start : span.end]):
                self.keep_damaged += 1
                if len(self.keep_damaged_examples) < 12:
                    self.keep_damaged_examples.append(doc.text[span.start : span.end])

    def leak_rate(self, label: str | None = None) -> float:
        total = self.total[label] if label else sum(self.total.values())
        leaks = (
            (self.partial[label] + self.leaked[label])
            if label
            else sum(self.partial.values()) + sum(self.leaked.values())
        )
        return leaks / total if total else 0.0

    def as_dict(self) -> dict[str, Any]:
        per_type = {
            label: {
                "total": self.total[label],
                "protected": self.protected[label],
                "partial": self.partial[label],
                "leaked": self.leaked[label],
                "leak_rate": round(self.leak_rate(label), 4),
            }
            for label in sorted(self.total)
        }
        return {
            "docs": self.docs,
            "values": sum(self.total.values()),
            "leak_rate": round(self.leak_rate(), 4),
            "per_type": per_type,
            "out_of_scope": {
                label: {"total": n, "protected": self.out_of_scope_protected[label]}
                for label, n in sorted(self.out_of_scope.items())
            },
            "false_positives": self.false_positives,
            "false_positive_examples": self.false_positive_examples,
            "keep_total": self.keep_total,
            "keep_damaged": self.keep_damaged,
            "keep_damaged_examples": self.keep_damaged_examples,
            "ms_per_doc": round(1000 * self.seconds / self.docs, 1) if self.docs else 0.0,
        }


def _coverage(length: int, predicted: list[Entity]) -> list[bool]:
    covered = [False] * length
    for entity in predicted:
        for i in range(max(entity.start, 0), min(entity.end, length)):
            covered[i] = True
    return covered


def merge_scores(scores: list[Score]) -> Score:
    merged = Score()
    for s in scores:
        for attr in ("total", "protected", "partial", "leaked", "out_of_scope", "out_of_scope_protected"):
            getattr(merged, attr).update(getattr(s, attr))
        merged.false_positives += s.false_positives
        merged.keep_total += s.keep_total
        merged.keep_damaged += s.keep_damaged
        merged.docs += s.docs
        merged.seconds += s.seconds
    return merged


def group_by(items: list[Any], key: Any) -> dict[Any, list[Any]]:
    out: dict[Any, list[Any]] = defaultdict(list)
    for item in items:
        out[key(item)].append(item)
    return out
