"""GLiNER without PyTorch: the same model exported to ONNX, run with onnxruntime.

The pre- and post-processing mirror the `gliner` library (word splitting, prompt, first-subtoken word mask,
spans up to `max_width` words, greedy non-overlapping decoding). Measured against `gliner` + PyTorch on 63
English/German texts:

    onnx/model.onnx       fp32, 1.16 GB   identical 63/63, ~2x faster
    onnx/model_fp16.onnx  fp16, 0.58 GB   identical 63/63, ~1.3x faster   <- default
    onnx/model_q4f16.onnx       0.47 GB   53/63
    onnx/model_int8.onnx        0.35 GB   misses almost everything (don't use)

Files are downloaded once from Hugging Face into ~/.cache/hushmask/models.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_REPO = "onnx-community/gliner_multi_pii-v1"
DEFAULT_FILE = "onnx/model_fp16.onnx"
CACHE = Path.home() / ".cache" / "hushmask" / "models"
_WORDS = re.compile(r"\w+(?:[-_]\w+)*|\S")  # same splitter as gliner's WhitespaceTokenSplitter


def is_cached(repo: str = DEFAULT_REPO, model_file: str = DEFAULT_FILE) -> bool:
    """True once the model has been downloaded, so the first-use wait is over."""
    return (CACHE / repo / model_file).exists()


def _download(repo: str, filename: str) -> Path:
    path = CACHE / repo / filename
    if not path.exists():
        if filename.endswith(".onnx"):
            print(f"[hushmask] downloading the names model ({repo}, ~0.6 GB, only once)...", file=sys.stderr)
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
        request = urllib.request.Request(url, headers={"User-Agent": "hushmask"})
        tmp = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(request, timeout=600) as response, tmp.open("wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
        tmp.replace(path)
    return path


class OnnxGliner:
    """Drop-in for `gliner.GLiNER.predict_entities`, for the span-based GLiNER models."""

    def __init__(self, repo: str = DEFAULT_REPO, model_file: str = DEFAULT_FILE) -> None:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        config = json.loads(_download(repo, "gliner_config.json").read_text(encoding="utf-8"))
        self.max_width = int(config.get("max_width", 12))
        self.max_len = int(config.get("max_len", 384))
        self.ent_token = config.get("ent_token", "<<ENT>>")
        self.sep_token = config.get("sep_token", "<<SEP>>")
        self.tokenizer = Tokenizer.from_file(str(_download(repo, "tokenizer.json")))
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(_download(repo, model_file)), options, providers=["CPUExecutionProvider"]
        )

    def predict_entities(self, text: str, labels: list[str], threshold: float = 0.5) -> list[dict[str, Any]]:
        np = self._np
        words = [(m.group(), m.start(), m.end()) for m in _WORDS.finditer(text)][: self.max_len]
        if not words or not labels:
            return []
        prompt: list[str] = []
        for label in labels:
            prompt += [self.ent_token, label]
        prompt.append(self.sep_token)

        encoding = self.tokenizer.encode(prompt + [w for w, _, _ in words], is_pretokenized=True)
        words_mask, previous = [], None
        for word_id in encoding.word_ids:
            if word_id is None or word_id < len(prompt) or word_id == previous:
                words_mask.append(0)
            else:
                words_mask.append(word_id - len(prompt) + 1)
            previous = word_id

        n = len(words)
        starts = np.repeat(np.arange(n), self.max_width)
        ends = starts + np.tile(np.arange(self.max_width), n)
        inputs = {
            "input_ids": np.array([encoding.ids], dtype=np.int64),
            "attention_mask": np.array([encoding.attention_mask], dtype=np.int64),
            "words_mask": np.array([words_mask], dtype=np.int64),
            "text_lengths": np.array([[n]], dtype=np.int64),
            "span_idx": np.stack([starts, ends], axis=-1)[None].astype(np.int64),
            "span_mask": (ends < n)[None],
        }
        logits = self.session.run(["logits"], inputs)[0][0]  # [words, max_width, classes]
        probs = 1.0 / (1.0 + np.exp(-logits))

        candidates = []
        for i, j, c in zip(*np.nonzero(probs > threshold), strict=True):
            if i + j < n:
                candidates.append((float(probs[i, j, c]), int(i), int(i + j), int(c)))
        candidates.sort(key=lambda x: -x[0])
        chosen: list[tuple[float, int, int, int]] = []
        for cand in candidates:  # flat NER: keep the best spans that don't overlap
            if all(cand[2] < other[1] or cand[1] > other[2] for other in chosen):
                chosen.append(cand)
        chosen.sort(key=lambda x: x[1])
        return [
            {
                "start": words[i][1],
                "end": words[j][2],
                "text": text[words[i][1] : words[j][2]],
                "label": labels[c],
                "score": score,
            }
            for score, i, j, c in chosen
        ]
