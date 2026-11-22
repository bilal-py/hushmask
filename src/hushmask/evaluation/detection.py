"""Leak and over-masking evaluation across detector setups (patterns → + your list → + names model)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..detectors import Detector
from ..masker import Masker
from ..policy import PRESETS, Policy
from .metrics import Doc, Score


@dataclass(frozen=True)
class Setup:
    name: str
    use_known: bool
    use_model: bool


SETUPS = [
    Setup("patterns", use_known=False, use_model=False),
    Setup("patterns + your list", use_known=True, use_model=False),
    Setup("patterns + your list + names model", use_known=True, use_model=True),
]


def evaluate(
    docs: list[Doc],
    *,
    preset: str,
    model: Detector | None = None,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    policy = Policy.preset(preset)
    in_scope = {str(t) for t in PRESETS[preset]}
    has_known = any(d.known for d in docs)
    results: dict[str, Any] = {}
    for setup in SETUPS:
        if setup.use_model and model is None:
            continue
        if setup.use_known and not has_known and not setup.use_model:
            continue  # no user lists in this dataset: identical to "patterns"
        score = Score()
        started = time.perf_counter()
        for i, doc in enumerate(docs):
            masker = Masker(
                policy=policy,
                known=doc.known if setup.use_known else (),
                extra_detectors=[model] if setup.use_model and model else [],
            )
            score.add(doc, masker.detect(doc.text), in_scope)
            if (i + 1) % 100 == 0:
                progress(f"{setup.name}: {i + 1}/{len(docs)}")
        score.seconds = time.perf_counter() - started
        name = setup.name if has_known else setup.name.replace(" + your list", "")
        results[name] = score.as_dict()
    return results
