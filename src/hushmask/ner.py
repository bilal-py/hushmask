"""Model-based detection for names, addresses and places that no pattern or list can catch.

Needs the optional extra: `uv sync --extra ner` (or `pip install hushmask[ner]`). That runs the model
with onnxruntime (~600 MB with the model, see `onnx_ner.py`). The `ner-torch` extra runs the same model
with PyTorch instead (~1.8 GB). Either way it's downloaded on first use and runs locally on CPU.

Bank statements are hard for NER models: they are ALL CAPS and glue words together
(`NEFT-SUNITA RAO-REFUND`). So the model reads a *view* of the text in which separators become
spaces and mostly-upper-case lines are title-cased. The view has exactly the same length as the
original, so the model's character offsets map straight back.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Iterator, Mapping
from typing import Any, Protocol

from .detectors import PRIORITY_MODEL
from .entities import Entity, EntityType

DEFAULT_MODEL = "urchade/gliner_multi_pii-v1"


def onnx_available() -> bool:
    return all(importlib.util.find_spec(m) is not None for m in ("onnxruntime", "tokenizers", "numpy"))


def torch_available() -> bool:
    return importlib.util.find_spec("gliner") is not None


def available() -> bool:
    """True if either backend for the names model is installed."""
    return onnx_available() or torch_available()


# "organization" is deliberately absent: on statements it means merchants, which the AI needs.
DEFAULT_LABELS: dict[str, EntityType] = {
    "person": EntityType.PERSON,
    "street address": EntityType.ADDRESS,
    "city": EntityType.LOCATION,
}

_SEPARATORS = re.compile(r"[-/*_|]")
_WORD = re.compile(r"[^\s\-/*_|]+")
# Banking words that the model sometimes pulls into a name span: "NEFT-SUNITA RAO-REFUND".
_EDGE_NOISE = frozenset(
    {
        *("neft", "imps", "rtgs", "upi", "sepa", "ach", "ecs", "nach", "pos", "atm", "trf", "transfer"),
        *("to", "from", "by", "via", "ref", "refund", "salary", "rent", "payment", "paid", "credit", "debit"),
        *("paypal", "überweisung", "an"),
    }
)
# Debit/credit markers, only trimmed from the end: a leading "Dr." is a title.
_TRAILING_NOISE = _EDGE_NOISE | {"dr", "cr"}


class NerModel(Protocol):
    def predict_entities(self, text: str, labels: list[str], threshold: float = ...) -> list[dict[str, Any]]: ...


def model_view(text: str, upper_ratio: float = 0.7) -> str:
    """Same-length copy of `text` that NER models read better."""
    lines = []
    for line in _SEPARATORS.sub(" ", text).split("\n"):
        letters = [c for c in line if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) >= upper_ratio:
            titled = line.title()
            if len(titled) == len(line):  # a few characters change length when re-cased
                line = titled
        lines.append(line)
    return "\n".join(lines)


def chunks(text: str, max_chars: int) -> Iterator[tuple[int, str]]:
    """Split on line breaks into pieces of at most ~max_chars, yielding (offset, piece)."""
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            cut = text.rfind("\n", start, end)
            if cut <= start:
                cut = text.rfind(" ", start, end)
            if cut > start:
                end = cut + 1
        yield start, text[start:end]
        start = end


def trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Drop banking words and punctuation from the edges of a model span."""
    words = [(m.start(), m.end()) for m in _WORD.finditer(text, start, end)]

    def word(span: tuple[int, int]) -> str:
        return text[span[0] : span[1]].casefold().strip(".,:;")

    while words and word(words[0]) in _EDGE_NOISE:
        words.pop(0)
    while words and word(words[-1]) in _TRAILING_NOISE:
        words.pop()
    if not words:
        return start, start
    start, end = words[0][0], words[-1][1]
    while end > start and text[end - 1] in ",;:":
        end -= 1
    return start, end


class GlinerDetector:
    name = "gliner"
    deterministic = False

    def __init__(
        self,
        model: str | NerModel = DEFAULT_MODEL,
        *,
        labels: Mapping[str, EntityType] | None = None,
        threshold: float = 0.5,
        chunk_chars: int = 1500,
        backend: str = "auto",
    ) -> None:
        """`backend`: "onnx" (onnxruntime, small), "torch" (gliner + PyTorch), or "auto" (onnx if installed)."""
        self._model_name = model if isinstance(model, str) else None
        self._model: NerModel | None = None if isinstance(model, str) else model
        self.labels = dict(labels or DEFAULT_LABELS)
        self.threshold = threshold
        self.chunk_chars = chunk_chars
        self.backend = backend

    @property
    def model(self) -> NerModel:
        if self._model is None:
            backend = self.backend
            if backend == "auto":
                backend = "onnx" if onnx_available() else "torch" if torch_available() else "none"
            if backend == "onnx":
                from .onnx_ner import DEFAULT_REPO, OnnxGliner

                # The default PyTorch model and the ONNX repo are the same weights.
                repo = DEFAULT_REPO if self._model_name == DEFAULT_MODEL else self._model_name
                self._model = OnnxGliner(repo)
            elif backend == "torch":
                from gliner import GLiNER

                self._model = GLiNER.from_pretrained(self._model_name)
            else:
                raise ImportError(
                    "Model-based detection needs the 'ner' extra: uv sync --extra ner (or pip install hushmask[ner])"
                )
        return self._model

    def detect(self, text: str) -> list[Entity]:
        view = model_view(text)
        labels = list(self.labels)
        # The model sometimes tags the label word itself ("the person or merchant" as a person).
        label_words = {w for label in labels for w in label.casefold().split()}
        found: list[Entity] = []
        for offset, piece in chunks(view, self.chunk_chars):
            if not piece.strip():
                continue
            for p in self.model.predict_entities(piece, labels, threshold=self.threshold):
                entity_type = self.labels.get(p["label"])
                if entity_type is None:
                    continue
                start, end = trim_span(text, offset + p["start"], offset + p["end"])
                value = text[start:end]
                # Fewer than 2 letters ("M", "J.") is noise the evaluation kept finding, not a name.
                if sum(c.isalpha() for c in value) < 2:
                    continue
                if start < end and not label_words & {w.casefold() for w in _WORD.findall(value)}:
                    found.append(Entity(entity_type, start, end, text[start:end], self.name, PRIORITY_MODEL))
        return found
