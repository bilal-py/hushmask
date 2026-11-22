"""Does masking cost the AI accuracy? Categorize the same synthetic statements with and without hushmask.

Needs an OpenAI-compatible endpoint (e.g. Ollama) and the 'proxy' extra (httpx). Each statement is one
request per condition, so keep `n` small on a CPU-only model.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from ..detectors import Detector
from ..masker import Masker
from ..policy import Policy
from ..proxy.openai import mask_request, restore_response
from .metrics import Doc
from .synthetic import CATEGORIES, Transaction

INSTRUCTION = (
    "You categorize bank statement transactions. For every transaction line, in the order they appear, return "
    "the counterparty (the merchant or person) and one category from this list: " + ", ".join(CATEGORIES) + ". "
    "Money received from a person as pay is Income; money sent to a person for housing is Rent; money returned is "
    "Refund; any other money to or from a person is Transfer."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "counterparty": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                },
                "required": ["counterparty", "category"],
            },
        }
    },
    "required": ["transactions"],
}


def evaluate(
    docs: list[Doc],
    *,
    upstream_url: str,
    model: str,
    api_key: str | None = None,
    ner: Detector | None = None,
    timeout: float = 900.0,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    import httpx

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = f"{upstream_url.rstrip('/')}/chat/completions"
    conditions = {"without hushmask": [], "with hushmask": []}
    timings = {name: 0.0 for name in conditions}

    with httpx.Client(timeout=timeout, headers=headers) as client:
        for i, doc in enumerate(docs):
            body = {
                "model": model,
                "temperature": 0,
                "messages": [{"role": "system", "content": INSTRUCTION}, {"role": "user", "content": doc.text}],
                "response_format": {"type": "json_schema", "json_schema": {"name": "categories", "schema": SCHEMA}},
            }
            for name in conditions:
                started = time.perf_counter()
                if name == "with hushmask":
                    masker = Masker(
                        policy=Policy.preset("finance"), known=doc.known, extra_detectors=[ner] if ner else []
                    )
                    masked, _ = mask_request(body, masker)
                    response = client.post(url, json=masked).raise_for_status().json()
                    response, _ = restore_response(response, masker)
                else:
                    response = client.post(url, json=body).raise_for_status().json()
                timings[name] += time.perf_counter() - started
                conditions[name].append(_parse(response))
            progress(f"statement {i + 1}/{len(docs)}")

    results: dict[str, Any] = {"model": model, "statements": len(docs), "conditions": {}}
    for name, answers in conditions.items():
        results["conditions"][name] = _score(docs, answers) | {
            "seconds_per_statement": round(timings[name] / len(docs), 1)
        }
    return results


def _parse(response: dict[str, Any]) -> list[dict[str, str]]:
    content = (response.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    try:
        return list(json.loads(content).get("transactions", []))
    except (ValueError, AttributeError):
        return []


def _score(docs: list[Doc], answers: list[list[dict[str, str]]]) -> dict[str, Any]:
    total = correct = people = people_named = count_mismatch = 0
    confusions: dict[str, int] = {}
    for doc, answer in zip(docs, answers, strict=True):
        truth: list[Transaction] = doc.meta["transactions"]
        if len(answer) != len(truth):
            count_mismatch += 1
        for i, tx in enumerate(truth):
            total += 1
            got = answer[i] if i < len(answer) else {}
            if got.get("category") == tx.category:
                correct += 1
            else:
                key = f"{tx.category} → {got.get('category', 'missing')}"
                confusions[key] = confusions.get(key, 0) + 1
            if tx.is_person:
                people += 1
                if tx.counterparty.casefold() in str(got.get("counterparty", "")).casefold():
                    people_named += 1
    return {
        "transactions": total,
        "category_accuracy": round(correct / total, 4) if total else 0.0,
        "people_named_correctly": round(people_named / people, 4) if people else None,
        "statements_with_wrong_count": count_mismatch,
        "top_mistakes": dict(sorted(confusions.items(), key=lambda kv: -kv[1])[:6]),
    }
