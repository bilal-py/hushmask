"""The ai4privacy `pii-masking-400k` validation split, as an outside test hushmask wasn't built around.

Licence: academic and non-commercial use only, no redistribution (see the dataset's LICENSE). So the file is
downloaded on demand into a local cache and never committed; only aggregate scores are published, with
credit to Ai4Privacy.
"""

from __future__ import annotations

import json
import random
import urllib.request
from pathlib import Path

from ..entities import EntityType as T
from .metrics import Doc, Span

BASE_URL = "https://huggingface.co/datasets/ai4privacy/pii-masking-400k/resolve/main/data/validation/{file}"
FILES = {"en": "1en.jsonl", "de": "de.jsonl", "fr": "fr.jsonl", "es": "es.jsonl", "it": "it.jsonl", "nl": "nl.jsonl"}
CACHE = Path.home() / ".cache" / "hushmask" / "ai4privacy"

# Their labels → ours. Anything else is reported as "not claimed": hushmask doesn't promise to find it.
LABELS = {
    "GIVENNAME": T.PERSON,
    "SURNAME": T.PERSON,
    "EMAIL": T.EMAIL,
    "TELEPHONENUM": T.PHONE,
    "CREDITCARDNUMBER": T.CARD,
    "STREET": T.ADDRESS,
    "BUILDINGNUM": T.ADDRESS,
    "CITY": T.LOCATION,
}


def load(language: str = "en", n: int = 500, seed: int = 7) -> list[Doc]:
    path = _download(language)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    sample = random.Random(seed).sample(rows, min(n, len(rows)))
    return [_doc(row) for row in sample]


def _doc(row: dict) -> Doc:
    gold = [Span(str(LABELS.get(m["label"], m["label"])), m["start"], m["end"]) for m in row["privacy_mask"]]
    return Doc(row["source_text"], gold, meta={"uid": row.get("uid"), "locale": row.get("locale")})


def _download(language: str) -> Path:
    if language not in FILES:
        raise ValueError(f"language must be one of {', '.join(FILES)}")
    path = CACHE / FILES[language]
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(BASE_URL.format(file=FILES[language]), headers={"User-Agent": "hushmask-eval"})
        with urllib.request.urlopen(request, timeout=120) as response:
            path.write_bytes(response.read())
    return path
