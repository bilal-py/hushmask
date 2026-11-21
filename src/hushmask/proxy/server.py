"""OpenAI-compatible privacy proxy, plus the local dashboard.

Point any OpenAI client's base URL at http://127.0.0.1:8700/v1. Each chat request is masked, sent to the
upstream, and the answer is restored before it goes back to the client. The dashboard lives at /dashboard/.
"""

from __future__ import annotations

import importlib.util
import threading
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..entities import Entity
from ..masker import LeakError, Masker
from ..ner import GlinerDetector
from ..policy import Policy
from .config import AppConfig, ProxyConfig
from .openai import UnmaskableContent, error_body, mask_request, restore_response, to_sse
from .store import AppStore

WEB_DIST = Path(__file__).resolve().parent.parent / "web_dist"


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


class NerHolder:
    """Loads the model the first time anyone needs it (an app or the playground can turn NER on at runtime)."""

    def __init__(self, model: str, threshold: float) -> None:
        self.model_name = model
        self.threshold = threshold
        self.available = importlib.util.find_spec("gliner") is not None
        self._detector: _LockedDetector | None = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._detector is not None

    def get(self) -> _LockedDetector | None:
        if not self.available:
            return None
        with self._lock:
            if self._detector is None:
                inner = GlinerDetector(self.model_name, threshold=self.threshold)
                _ = inner.model
                self._detector = _LockedDetector(inner)
        return self._detector


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


@dataclass
class Runtime:
    config: ProxyConfig
    store: AppStore
    ner: NerHolder
    stats: defaultdict[str, AppStats] = field(default_factory=lambda: defaultdict(AppStats))
    client: httpx.AsyncClient | None = None

    @property
    def mode(self) -> str:
        if self.config.passthrough:
            return "passthrough"
        return "apps" if self.store.editable else "config"

    def masker(self, *, preset: str, known: Any, secret: bytes | None, ner: bool) -> Masker:
        detector = self.ner.get() if ner else None
        return Masker(
            policy=Policy.preset(preset), known=known, secret=secret, extra_detectors=[detector] if detector else []
        )

    def masker_for(self, app: AppConfig) -> Masker:
        return self.masker(preset=app.preset, known=app.known, secret=app.secret, ner=app.ner)


class _AuthError(Exception):
    pass


def create_app(
    config: ProxyConfig, *, store: AppStore | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    """`store` holds the apps (defaults to a read-only store over `config.apps`); `transport` lets tests
    replace the upstream with an in-memory fake."""
    rt = Runtime(
        config=config,
        store=store or AppStore(config.apps),
        ner=NerHolder(config.ner_model, config.ner_threshold),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if rt.store.uses_ner:
            await run_in_threadpool(rt.ner.get)  # load once, before the first request
        async with httpx.AsyncClient(transport=transport, timeout=config.timeout) as client:
            rt.client = client
            yield

    app = FastAPI(title="hushmask", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runtime = rt

    def resolve(request: Request) -> tuple[AppConfig, str | None]:
        """Which app is calling, and the Authorization header to send upstream."""
        auth = request.headers.get("authorization", "")
        if config.passthrough:
            return rt.store.get("default"), auth or None  # type: ignore[return-value]
        presented = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
        app_config = rt.store.find_by_key(presented)
        if app_config is None:
            raise _AuthError
        key = app_config.upstream_key()
        return app_config, f"Bearer {key}" if key else None

    @app.exception_handler(_AuthError)
    async def auth_error(_: Request, __: _AuthError) -> JSONResponse:
        return JSONResponse(
            error_body("Unknown hushmask app key", "invalid_request_error", "invalid_api_key"), status_code=401
        )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "mode": rt.mode, "apps": [a.name for a in rt.store.all()], "ner": rt.ner.loaded}

    @app.get("/hushmask/stats")
    async def get_stats() -> dict[str, Any]:
        return {name: s.as_dict() for name, s in rt.stats.items()}

    @app.get("/v1/models")
    async def models(request: Request) -> Response:
        app_config, upstream_auth = resolve(request)
        upstream = await rt.client.get(f"{app_config.upstream_url}/models", headers=_auth_header(upstream_auth))
        return Response(upstream.content, upstream.status_code, media_type="application/json")

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Response:
        app_config, upstream_auth = resolve(request)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(error_body("Body is not valid JSON", "invalid_request_error"), status_code=400)
        outcome = await forward_chat(rt, app_config, body, upstream_auth)
        if outcome.error is not None:
            return outcome.error
        headers = {
            "X-Hushmask-Masked": str(sum(outcome.counts.values())),
            "X-Hushmask-Unknown-Tokens": str(len(outcome.unknown)),
        }
        if body.get("stream"):
            return StreamingResponse(to_sse(outcome.restored), media_type="text/event-stream", headers=headers)
        return JSONResponse(outcome.restored, headers=headers)

    from .admin import router as admin_router

    app.include_router(admin_router)
    _mount_dashboard(app)
    return app


@dataclass
class ChatOutcome:
    error: Response | None = None
    masked_request: dict[str, Any] | None = None
    masked_response: dict[str, Any] | None = None
    restored: dict[str, Any] = field(default_factory=dict)
    counts: Counter[str] = field(default_factory=Counter)
    unknown: set[str] = field(default_factory=set)


async def forward_chat(
    rt: Runtime, app_config: AppConfig, body: dict[str, Any], upstream_auth: str | None
) -> ChatOutcome:
    """Mask → upstream → restore. Shared by the proxy endpoint and the dashboard's round trip."""
    app_stats = rt.stats[app_config.name]
    app_stats.requests += 1
    try:
        masker = await run_in_threadpool(rt.masker_for, app_config)
        masked, counts = await run_in_threadpool(
            mask_request,
            body,
            masker,
            allow_images=app_config.allow_images,
            placeholder_note=app_config.placeholder_note,
        )
    except UnmaskableContent as err:
        app_stats.blocked_unmaskable += 1
        return ChatOutcome(JSONResponse(error_body(str(err), "invalid_request_error", "unmaskable_content"), 400))
    except LeakError as err:
        app_stats.blocked_leaks += 1
        return ChatOutcome(JSONResponse(error_body(str(err), "hushmask_error", "pii_leak_blocked"), 422))
    app_stats.masked.update(counts)

    # Always ask upstream for the whole answer: a token split across stream chunks can't be restored.
    masked["stream"] = False
    masked.pop("stream_options", None)
    try:
        upstream = await rt.client.post(
            f"{app_config.upstream_url}/chat/completions", json=masked, headers=_auth_header(upstream_auth)
        )
    except httpx.HTTPError as err:
        app_stats.upstream_errors += 1
        message = f"Could not reach {app_config.upstream_url}: {type(err).__name__}"
        return ChatOutcome(JSONResponse(error_body(message, "upstream_error", "upstream_unreachable"), 502))
    if upstream.status_code >= 400:
        app_stats.upstream_errors += 1
        return ChatOutcome(Response(upstream.content, upstream.status_code, media_type="application/json"))

    raw = upstream.json()
    restored, unknown = restore_response(raw, masker)
    app_stats.unknown_tokens += len(unknown)
    return ChatOutcome(masked_request=masked, masked_response=raw, restored=restored, counts=counts, unknown=unknown)


def _auth_header(upstream_auth: str | None) -> dict[str, str]:
    return {"Authorization": upstream_auth} if upstream_auth else {}


def _mount_dashboard(app: FastAPI) -> None:
    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/dashboard/")

    if (WEB_DIST / "index.html").exists():
        app.mount("/dashboard", StaticFiles(directory=WEB_DIST, html=True), name="dashboard")
        return

    @app.get("/dashboard/{rest:path}", include_in_schema=False)
    async def not_built(rest: str = "") -> HTMLResponse:
        return HTMLResponse(
            "<h1>Dashboard not built</h1><p>Run <code>npm install &amp;&amp; npm run build</code> in "
            "<code>web/</code>, then restart <code>hushmask serve</code>. The proxy at <code>/v1</code> works "
            "without it.</p>",
            status_code=503,
        )
