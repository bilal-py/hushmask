"""Dashboard API under /hushmask/api.

It can create apps and show their keys, so it only answers requests that are clearly from this machine's
dashboard:

* the Host header must be localhost / 127.0.0.1 / [::1] (blocks DNS-rebinding attacks), and
* the request must carry `X-Hushmask-Admin: 1`. Browsers won't add a custom header to a cross-site request
  without a CORS preflight, which we never approve, so another website can't drive this API.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..detectors import KnownValue
from ..entities import EntityType
from ..masker import LeakError
from ..policy import PRESETS
from .config import AppConfig, ConfigError
from .store import known_to_specs

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}

# Shown as choices in the dashboard. All speak the OpenAI chat-completions API.
UPSTREAMS = [
    {"label": "OpenAI", "url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY"},
    {"label": "Gemini", "url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_env": "GEMINI_API_KEY"},
    {"label": "Ollama (local)", "url": "http://localhost:11434/v1", "key_env": ""},
    {"label": "OpenRouter", "url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY"},
    {"label": "Groq", "url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY"},
]


def admin_guard(request: Request) -> None:
    host = request.headers.get("host", "").rsplit(":", 1)[0].lower()
    if host not in LOCAL_HOSTS:
        raise HTTPException(403, "The dashboard API only answers on localhost")
    if request.headers.get("x-hushmask-admin") != "1":
        raise HTTPException(403, "Missing X-Hushmask-Admin header")


router = APIRouter(prefix="/hushmask/api", dependencies=[Depends(admin_guard)])


def _rt(request: Request) -> Any:
    return request.app.state.runtime


# -- info ---------------------------------------------------------------------------------------


@router.get("/info")
async def info(request: Request) -> dict[str, Any]:
    rt = _rt(request)
    return {
        "mode": rt.mode,
        "editable": rt.store.editable,
        "store_path": str(rt.store.path) if rt.store.path else None,
        "ner": {
            "available": rt.ner.available,
            "loaded": rt.ner.loaded,
            "cached": rt.ner.cached,
            "model": rt.ner.model_name,
        },
        "presets": {name: sorted(types) for name, types in PRESETS.items()},
        "entity_types": [t.value for t in EntityType],
        "upstreams": UPSTREAMS,
    }


# -- playground ---------------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    text: str = Field(max_length=200_000)
    preset: str = "finance"
    known: list[str] = []
    ner: bool = False


@router.post("/preview")
async def preview(request: Request, body: PreviewRequest) -> dict[str, Any]:
    """Show exactly what would be sent. Values only travel between this machine and its own browser."""
    rt = _rt(request)
    if body.preset not in PRESETS:
        raise HTTPException(400, f"Unknown preset {body.preset!r}")
    if body.ner and not rt.ner.available:
        raise HTTPException(400, "Model detection needs the 'ner' extra: uv sync --extra ner")
    known = [KnownValue.parse(s) for s in body.known if s.strip()]
    started = time.perf_counter()

    def run() -> Any:
        masker = rt.masker(preset=body.preset, known=known, secret=None, ner=body.ner)
        return masker.mask(body.text)

    try:
        result = await run_in_threadpool(run)
    except LeakError as err:
        raise HTTPException(422, str(err)) from err
    return {
        "masked": result.text,
        "entities": [
            {"type": e.type, "start": e.start, "end": e.end, "text": e.text, "detector": e.detector, "token": t}
            for e, t in zip(result.entities, result.tokens, strict=True)
        ],
        "took_ms": round((time.perf_counter() - started) * 1000),
    }


class RoundTripRequest(BaseModel):
    app: str
    model: str
    text: str = Field(max_length=200_000)
    instruction: str = ""
    api_key: str | None = None  # passthrough mode only; never stored


@router.post("/roundtrip")
async def roundtrip(request: Request, body: RoundTripRequest) -> dict[str, Any]:
    """Send text through an app exactly like a real client would, and show every stage."""
    from .server import forward_chat

    rt = _rt(request)
    app_config = rt.store.get(body.app)
    if app_config is None:
        raise HTTPException(404, f"No app called {body.app!r}")
    if rt.config.passthrough:
        upstream_auth = f"Bearer {body.api_key}" if body.api_key else None
    else:
        key = app_config.upstream_key()
        upstream_auth = f"Bearer {key}" if key else None

    messages = [{"role": "system", "content": body.instruction}] if body.instruction.strip() else []
    messages.append({"role": "user", "content": body.text})
    started = time.perf_counter()
    outcome = await forward_chat(rt, app_config, {"model": body.model, "messages": messages}, upstream_auth)
    took_ms = round((time.perf_counter() - started) * 1000)
    if outcome.error is not None:
        return {
            "ok": False,
            "status": outcome.error.status_code,
            "error": outcome.error.body.decode(),
            "took_ms": took_ms,
        }

    def content(response: dict[str, Any]) -> str:
        choices = response.get("choices") or [{}]
        return (choices[0].get("message") or {}).get("content") or ""

    sent = outcome.masked_request["messages"]
    return {
        "ok": True,
        "sent_messages": sent,
        "masked_answer": content(outcome.masked_response),
        "restored_answer": content(outcome.restored),
        "masked_counts": dict(outcome.counts),
        "unknown_tokens": sorted(outcome.unknown),
        "took_ms": took_ms,
    }


# -- apps ---------------------------------------------------------------------------------------


class AppSpec(BaseModel):
    upstream_url: str | None = None
    upstream_api_key: str | None = None
    upstream_api_key_env: str | None = None
    preset: str | None = None
    known: list[str] | None = None
    ner: bool | None = None
    allow_images: bool | None = None
    placeholder_note: bool | None = None

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class NewApp(AppSpec):
    name: str
    upstream_url: str


def _app_view(rt: Any, app: AppConfig) -> dict[str, Any]:
    env = app.upstream_api_key_env
    return {
        "name": app.name,
        "key": app.key,
        "upstream_url": app.upstream_url,
        "upstream_api_key_env": env,
        "has_stored_api_key": bool(app.upstream_api_key),
        "api_key_ready": app.upstream_key() is not None,
        "preset": app.preset,
        "known": known_to_specs(app.known),
        "ner": app.ner,
        "allow_images": app.allow_images,
        "placeholder_note": app.placeholder_note,
        "stats": rt.stats[app.name].as_dict(),
    }


def _store_call(fn: Any, *args: Any) -> AppConfig:
    try:
        return fn(*args)
    except ConfigError as err:
        raise HTTPException(400, str(err)) from err
    except KeyError as err:
        raise HTTPException(404, f"No app called {err.args[0]!r}") from err


@router.get("/apps")
async def list_apps(request: Request) -> list[dict[str, Any]]:
    rt = _rt(request)
    return [_app_view(rt, a) for a in rt.store.all()]


@router.post("/apps", status_code=201)
async def create_app_(request: Request, body: NewApp) -> dict[str, Any]:
    rt = _rt(request)
    spec = body.changes()
    name = spec.pop("name")
    app = _store_call(rt.store.create, name, spec)
    if app.ner:
        await run_in_threadpool(rt.ner.get)
    return _app_view(rt, app)


@router.put("/apps/{name}")
async def update_app(request: Request, name: str, body: AppSpec) -> dict[str, Any]:
    rt = _rt(request)
    app = _store_call(rt.store.update, name, body.changes())
    if app.ner:
        await run_in_threadpool(rt.ner.get)
    return _app_view(rt, app)


@router.post("/apps/{name}/rotate-key")
async def rotate_key(request: Request, name: str) -> dict[str, Any]:
    rt = _rt(request)
    return _app_view(rt, _store_call(rt.store.rotate_key, name))


@router.delete("/apps/{name}", status_code=204)
async def delete_app(request: Request, name: str) -> None:
    rt = _rt(request)
    _store_call(rt.store.delete, name)
    rt.stats.pop(name, None)
