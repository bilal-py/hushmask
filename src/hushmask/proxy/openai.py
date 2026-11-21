"""Mask OpenAI chat-completion requests and restore the responses. Pure functions, no I/O."""

from __future__ import annotations

import copy
import json
from collections import Counter
from collections.abc import Iterator
from typing import Any

from ..masker import Masker

PLACEHOLDER_NOTE = (
    "Some values in this conversation were replaced with placeholders such as PERSON_1a2b3c or EMAIL_9f8e7d "
    "for privacy. Treat each placeholder as the real value it stands for, and copy placeholders exactly, "
    "character for character, whenever you refer to them."
)
_UNMASKABLE_PARTS = {"image_url", "input_image", "input_audio", "file"}


class UnmaskableContent(Exception):
    """The request contains content we can't mask (images, audio, files)."""


def mask_request(
    body: dict[str, Any], masker: Masker, *, allow_images: bool = False, placeholder_note: bool = True
) -> tuple[dict[str, Any], Counter[str]]:
    """Return a masked copy of the request body and the number of masked values per type."""
    body = copy.deepcopy(body)
    counts: Counter[str] = Counter()

    for message in body.get("messages") or []:
        # System/developer messages are the app's instructions. Model-based detection there does more harm than
        # good ("the person or merchant" was masked as a name); patterns and known values still apply.
        use_models = message.get("role") not in ("system", "developer")

        def mask(text: str, use_models: bool = use_models) -> str:
            result = masker.mask(text, use_models=use_models)
            counts.update(str(e.type) for e in result.entities)
            return result.text

        content = message.get("content")
        if isinstance(content, str):
            message["content"] = mask(content)
        elif isinstance(content, list):
            for part in content:
                kind = part.get("type")
                if kind == "text" and isinstance(part.get("text"), str):
                    part["text"] = mask(part["text"])
                elif kind in _UNMASKABLE_PARTS and not allow_images:
                    raise UnmaskableContent(
                        f"'{kind}' content can't be masked, so it isn't sent. Enable allow_images for this app "
                        "to send it unmasked."
                    )
        if isinstance(message.get("name"), str):
            message["name"] = mask(message["name"])
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if isinstance(function.get("arguments"), str):
                function["arguments"] = mask(function["arguments"])

    if placeholder_note and counts:
        _add_note(body)
    return body, counts


def restore_response(body: dict[str, Any], masker: Masker) -> tuple[dict[str, Any], set[str]]:
    """Return a copy of the response with real values back, plus any token-like strings we couldn't restore."""
    body = copy.deepcopy(body)
    unknown: set[str] = set()
    for choice in body.get("choices") or []:
        message = choice.get("message") or {}
        for field in ("content", "refusal"):
            if isinstance(message.get(field), str):
                message[field] = _restore_text(message[field], masker, unknown)
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if isinstance(function.get("arguments"), str):
                function["arguments"] = _restore_text(function["arguments"], masker, unknown)
    return body, unknown


def to_sse(body: dict[str, Any]) -> Iterator[str]:
    """Turn a complete response into server-sent events, for clients that asked for `stream: true`.

    The upstream is always called without streaming (a token split across chunks can't be restored), so
    the whole answer arrives as one content chunk.
    """
    base = {k: body.get(k) for k in ("id", "created", "model", "system_fingerprint") if k in body}
    base["object"] = "chat.completion.chunk"
    for choice in body.get("choices") or []:
        index = choice.get("index", 0)
        message = choice.get("message") or {}
        delta: dict[str, Any] = {"role": message.get("role", "assistant")}
        if message.get("content") is not None:
            delta["content"] = message["content"]
        if message.get("tool_calls"):
            delta["tool_calls"] = [{"index": i, **call} for i, call in enumerate(message["tool_calls"])]
        yield _event({**base, "choices": [{"index": index, "delta": delta, "finish_reason": None}]})
        yield _event({**base, "choices": [{"index": index, "delta": {}, "finish_reason": choice.get("finish_reason")}]})
    if body.get("usage"):
        yield _event({**base, "choices": [], "usage": body["usage"]})
    yield "data: [DONE]\n\n"


def error_body(message: str, type_: str, code: str | None = None) -> dict[str, Any]:
    """OpenAI-style error, so clients surface our message instead of failing to parse."""
    return {"error": {"message": message, "type": type_, "code": code, "param": None}}


def _restore_text(text: str, masker: Masker, unknown: set[str]) -> str:
    """JSON (structured output, tool arguments) is restored value by value so quotes in real values can't
    break it; anything else is restored as plain text."""
    stripped = text.strip()
    if stripped[:1] in ("{", "["):
        try:
            parsed = json.loads(stripped)
        except ValueError:
            pass
        else:
            restored, info = masker.restore_json(parsed)
            unknown |= info.unknown
            return json.dumps(restored, ensure_ascii=False)
    result = masker.restore(text)
    unknown |= result.unknown
    return result.text


def _add_note(body: dict[str, Any]) -> None:
    messages = body.setdefault("messages", [])
    first = messages[0] if messages else None
    if first and first.get("role") in ("system", "developer"):
        if isinstance(first.get("content"), str):
            first["content"] = f"{first['content']}\n\n{PLACEHOLDER_NOTE}"
            return
        if isinstance(first.get("content"), list):
            first["content"].append({"type": "text", "text": PLACEHOLDER_NOTE})
            return
    messages.insert(0, {"role": "system", "content": PLACEHOLDER_NOTE})


def _event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
