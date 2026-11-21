"""Apps the dashboard can add, edit and remove, saved to a JSON file (default `~/.hushmask/apps.json`).

A TOML config (`--config`) gives a read-only store instead: the file stays the source of truth.

Provider API keys can be stored in the file, but an environment variable name is better: the file is
plain JSON on your disk. The token secret is stored so tokens stay the same across restarts.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..detectors import KnownValue
from ..policy import PRESETS
from .config import AppConfig, ConfigError

DEFAULT_STORE = Path.home() / ".hushmask" / "apps.json"
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_FIELDS = (
    "upstream_url",
    "upstream_api_key",
    "upstream_api_key_env",
    "preset",
    "known",
    "ner",
    "allow_images",
    "placeholder_note",
)


def new_key(name: str) -> str:
    return f"hm-{name}-{secrets.token_urlsafe(18)}"


def known_to_specs(known: Iterable[KnownValue]) -> list[str]:
    return [f"{k.type}={k.value}" for k in known]


class AppStore:
    def __init__(self, apps: Mapping[str, AppConfig] = (), *, path: Path | None = None, editable: bool = False):
        self._apps: dict[str, AppConfig] = dict(apps)
        self.path = path
        self.editable = editable
        self._lock = threading.Lock()

    @classmethod
    def open(cls, path: Path = DEFAULT_STORE) -> AppStore:
        apps: dict[str, AppConfig] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for raw in data.get("apps", []):
                app = _from_dict(raw)
                apps[app.name] = app
        return cls(apps, path=path, editable=True)

    # -- reads -------------------------------------------------------------------------------

    def all(self) -> list[AppConfig]:
        return sorted(self._apps.values(), key=lambda a: a.name)

    def get(self, name: str) -> AppConfig | None:
        return self._apps.get(name)

    def find_by_key(self, presented: str) -> AppConfig | None:
        if not presented:
            return None
        for app in self._apps.values():
            if app.key and hmac.compare_digest(app.key, presented):
                return app
        return None

    @property
    def uses_ner(self) -> bool:
        return any(a.ner for a in self._apps.values())

    # -- writes ------------------------------------------------------------------------------

    def create(self, name: str, spec: Mapping[str, Any]) -> AppConfig:
        self._check_editable()
        if not _NAME.match(name):
            raise ConfigError("name: use 1-40 lowercase letters, digits or dashes, starting with a letter or digit")
        with self._lock:
            if name in self._apps:
                raise ConfigError(f"an app called {name!r} already exists")
            app = _validated(AppConfig(name=name, upstream_url="", key=new_key(name)), spec)
            self._apps[name] = app
            self._save()
        return app

    def update(self, name: str, spec: Mapping[str, Any]) -> AppConfig:
        self._check_editable()
        with self._lock:
            current = self._require(name)
            app = _validated(current, spec)
            self._apps[name] = app
            self._save()
        return app

    def rotate_key(self, name: str) -> AppConfig:
        self._check_editable()
        with self._lock:
            app = replace(self._require(name), key=new_key(name))
            self._apps[name] = app
            self._save()
        return app

    def delete(self, name: str) -> None:
        self._check_editable()
        with self._lock:
            self._require(name)
            del self._apps[name]
            self._save()

    # -- internals ---------------------------------------------------------------------------

    def _require(self, name: str) -> AppConfig:
        app = self._apps.get(name)
        if app is None:
            raise KeyError(name)
        return app

    def _check_editable(self) -> None:
        if not self.editable:
            raise ConfigError("apps come from a config file; edit the file instead")

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {"apps": [_to_dict(a) for a in self.all()]}
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic: a crash never leaves half a file


def _validated(base: AppConfig, spec: Mapping[str, Any]) -> AppConfig:
    changes: dict[str, Any] = {k: spec[k] for k in _FIELDS if k in spec}
    if "known" in changes:
        changes["known"] = tuple(KnownValue.parse(s) for s in changes["known"] if str(s).strip())
    for key in ("upstream_api_key", "upstream_api_key_env"):
        if key in changes:
            changes[key] = (changes[key] or "").strip() or None
    app = replace(base, **changes)
    url = app.upstream_url.strip().rstrip("/")
    if not re.match(r"^https?://", url):
        raise ConfigError("upstream_url must start with http:// or https://")
    if app.preset not in PRESETS:
        raise ConfigError(f"unknown preset {app.preset!r} (choose from {', '.join(PRESETS)})")
    return replace(app, upstream_url=url)


def _to_dict(app: AppConfig) -> dict[str, Any]:
    return {
        "name": app.name,
        "key": app.key,
        "upstream_url": app.upstream_url,
        "upstream_api_key": app.upstream_api_key,
        "upstream_api_key_env": app.upstream_api_key_env,
        "preset": app.preset,
        "known": known_to_specs(app.known),
        "ner": app.ner,
        "allow_images": app.allow_images,
        "placeholder_note": app.placeholder_note,
        "secret": app.secret.hex(),
    }


def _from_dict(raw: Mapping[str, Any]) -> AppConfig:
    return AppConfig(
        name=raw["name"],
        key=raw["key"],
        upstream_url=raw["upstream_url"],
        upstream_api_key=raw.get("upstream_api_key"),
        upstream_api_key_env=raw.get("upstream_api_key_env"),
        preset=raw.get("preset", "strict"),
        known=tuple(KnownValue.parse(s) for s in raw.get("known", [])),
        ner=bool(raw.get("ner", False)),
        allow_images=bool(raw.get("allow_images", False)),
        placeholder_note=bool(raw.get("placeholder_note", True)),
        secret=bytes.fromhex(raw["secret"]),
    )
