"""OpenAI-compatible privacy proxy.

Point any OpenAI client's base URL at http://127.0.0.1:8700/v1. Each chat request is masked, sent to the
upstream, and the answer is restored before it goes back to the client.
"""

from __future__ import annotations

import hmac
import threading
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..entities import Entity
from ..masker import LeakError, Masker
from ..ner import GlinerDetector
from ..policy import Policy
from .config import AppConfig, ProxyConfig
from .openai import UnmaskableContent, error_body, mask_request, restore_response, to_sse


class _LockedDetector:
    """One shared model for all requests; torch inference isn't guaranteed thread-safe."""

    deterministic = False

    def __init__(self, inner: GlinerDetector) -> None:
        self.inner = inner
        self.name = inner.name
        self._lock = threading.Lock()

    def detect(self, text: str) -> list[Entity]:
        with self._lock:
            return self.inner.detect(text)


@dataclass
class AppStats:
    """Counts only. Never values."""

    requests: int = 0
    masked: Counter[str] = field(default_factory=Counter)
    blocked_leaks: int = 0
    blocked_unmaskable: int = 0
    unknown_tokens: int = 0
    upstream_errors: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "masked": dict(self.masked)}


class _AuthError(Exception):
    pass


def create_app(config: ProxyConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """`transport` lets tests replace the upstream with an in-memory fake."""
    stats = {name: AppStats() for name in config.apps}
    state: dict[str, Any] = {"ner": None}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if config.uses_ner:
            detector = GlinerDetector(config.ner_model, threshold=config.ner_threshold)
            await run_in_threadpool(lambda: detector.model)  # load once, before the first request
            state["ner"] = _LockedDetector(detector)
        async with httpx.AsyncClient(transport=transport, timeout=config.timeout) as client:
            state["client"] = client
            yield

    app = FastAPI(title="hushmask proxy", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def resolve(request: Request) -> tuple[AppConfig, str | None]:
        """Which app is calling, and the Authorization header to send upstream."""
        auth = request.headers.get("authorization", "")
        if config.passthrough:
            return config.apps["default"], auth or None
        presented = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
        for app_config in config.apps.values():
            if app_config.key and presented and hmac.compare_digest(app_config.key, presented):
                upstream_auth = f"Bearer {app_config.upstream_api_key}" if app_config.upstream_api_key else None
                return app_config, upstream_auth
        raise _AuthError

    def headers_for(upstream_auth: str | None) -> dict[str, str]:
        return {"Authorization": upstream_auth} if upstream_auth else {}

    def masker_for(app_config: AppConfig) -> Masker:
        extra = [state["ner"]] if app_config.ner and state["ner"] else []
        return Masker(
            policy=Policy.preset(app_config.preset),
            known=app_config.known,
            secret=app_config.secret,
            extra_detectors=extra,
        )

    @app.exception_handler(_AuthError)
    async def auth_error(_: Request, __: _AuthError) -> JSONResponse:
        return JSONResponse(
            error_body("Unknown hushmask app key", "invalid_request_error", "invalid_api_key"), status_code=401
        )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "apps": list(config.apps), "ner": config.uses_ner}

    @app.get("/hushmask/stats")
    async def get_stats() -> dict[str, Any]:
        return {name: s.as_dict() for name, s in stats.items()}

    @app.get("/v1/models")
    async def models(request: Request) -> Response:
        app_config, upstream_auth = resolve(request)
        upstream = await state["client"].get(f"{app_config.upstream_url}/models", headers=headers_for(upstream_auth))
        return Response(upstream.content, upstream.status_code, media_type="application/json")

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Response:
        app_config, upstream_auth = resolve(request)
        app_stats = stats[app_config.name]
        app_stats.requests += 1
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(error_body("Body is not valid JSON", "invalid_request_error"), status_code=400)
        wants_stream = bool(body.get("stream"))
        masker = masker_for(app_config)

        try:
            masked, counts = await run_in_threadpool(
                mask_request,
                body,
                masker,
                allow_images=app_config.allow_images,
                placeholder_note=app_config.placeholder_note,
            )
        except UnmaskableContent as err:
            app_stats.blocked_unmaskable += 1
            return JSONResponse(error_body(str(err), "invalid_request_error", "unmaskable_content"), status_code=400)
        except LeakError as err:
            app_stats.blocked_leaks += 1
            return JSONResponse(error_body(str(err), "hushmask_error", "pii_leak_blocked"), status_code=422)
        app_stats.masked.update(counts)

        # Always ask upstream for the whole answer: a token split across stream chunks can't be restored.
        masked["stream"] = False
        masked.pop("stream_options", None)
        upstream = await state["client"].post(
            f"{app_config.upstream_url}/chat/completions", json=masked, headers=headers_for(upstream_auth)
        )
        if upstream.status_code >= 400:
            app_stats.upstream_errors += 1
            return Response(upstream.content, upstream.status_code, media_type="application/json")

        restored, unknown = restore_response(upstream.json(), masker)
        app_stats.unknown_tokens += len(unknown)
        headers = {"X-Hushmask-Masked": str(sum(counts.values())), "X-Hushmask-Unknown-Tokens": str(len(unknown))}
        if wants_stream:
            return StreamingResponse(to_sse(restored), media_type="text/event-stream", headers=headers)
        return JSONResponse(restored, headers=headers)

    return app
