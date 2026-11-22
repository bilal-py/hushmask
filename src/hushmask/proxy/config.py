"""Proxy configuration.

Two modes:

* **Passthrough** (no config file): one implicit app. The client's own `Authorization` header is forwarded
  to the upstream, so `hushmask serve --upstream https://api.openai.com/v1` just works.
* **Apps** (`hushmask.toml`): each app gets its own hushmask key, upstream and masking rules. The upstream
  API key lives in the proxy (ideally via an environment variable), never in the app.

```toml
timeout = 600

[apps.spence]
key = "hm-spence-change-me"
upstream_url = "https://generativelanguage.googleapis.com/v1beta/openai"
upstream_api_key_env = "GEMINI_API_KEY"
preset = "finance"
known = ["PERSON=Lena Hoffmann", "ADDRESS=Bergstraße 12, 10115 Berlin"]
ner = true

[apps.notes]
key = "hm-notes-change-me"
upstream_url = "http://localhost:11434/v1"   # Ollama
preset = "strict"
```
"""

from __future__ import annotations

import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..detectors import KnownValue
from ..ner import DEFAULT_MODEL
from ..policy import PRESETS


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class AppConfig:
    name: str
    upstream_url: str
    key: str | None = None
    upstream_api_key: str | None = None
    upstream_api_key_env: str | None = None
    preset: str = "strict"
    known: tuple[KnownValue, ...] = ()
    ner: bool = False
    allow_images: bool = False
    placeholder_note: bool = True
    # Same secret for every request of this app, so the same value gets the same token across a whole
    # conversation (history is re-masked on every call) and the provider's prompt cache keeps working.
    secret: bytes = field(default_factory=lambda: secrets.token_bytes(32), repr=False)

    def upstream_key(self) -> str | None:
        """Read at request time, so an environment variable set after startup still works."""
        if self.upstream_api_key_env:
            return os.environ.get(self.upstream_api_key_env) or None
        return self.upstream_api_key


@dataclass(frozen=True)
class ProxyConfig:
    apps: dict[str, AppConfig]
    passthrough: bool = False
    timeout: float = 600.0
    ner_model: str = DEFAULT_MODEL
    ner_threshold: float = 0.5

    @property
    def uses_ner(self) -> bool:
        return any(a.ner for a in self.apps.values())


def passthrough_config(
    upstream_url: str,
    *,
    preset: str = "strict",
    known: tuple[KnownValue, ...] = (),
    ner: bool = False,
    allow_images: bool = False,
    timeout: float = 600.0,
    ner_model: str = DEFAULT_MODEL,
    ner_threshold: float = 0.5,
) -> ProxyConfig:
    _check_preset(preset, "default")
    app = AppConfig("default", upstream_url.rstrip("/"), preset=preset, known=known, ner=ner, allow_images=allow_images)
    return ProxyConfig(
        {"default": app}, passthrough=True, timeout=timeout, ner_model=ner_model, ner_threshold=ner_threshold
    )


def load_config(path: str | Path) -> ProxyConfig:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    raw_apps: dict[str, Any] = data.get("apps") or {}
    if not raw_apps:
        raise ConfigError("config has no [apps.<name>] sections")

    apps: dict[str, AppConfig] = {}
    seen_keys: set[str] = set()
    for name, raw in raw_apps.items():
        key = _required(raw, "key", name)
        if key in seen_keys:
            raise ConfigError(f"app {name!r}: key is used by another app")
        seen_keys.add(key)
        preset = raw.get("preset", "strict")
        _check_preset(preset, name)
        secret_hex = raw.get("secret")
        apps[name] = AppConfig(
            name=name,
            key=key,
            upstream_url=_required(raw, "upstream_url", name).rstrip("/"),
            upstream_api_key=raw.get("upstream_api_key"),
            upstream_api_key_env=_upstream_key_env(raw, name),
            preset=preset,
            known=tuple(KnownValue.parse(s) for s in raw.get("known", [])),
            ner=bool(raw.get("ner", False)),
            allow_images=bool(raw.get("allow_images", False)),
            placeholder_note=bool(raw.get("placeholder_note", True)),
            **({"secret": bytes.fromhex(secret_hex)} if secret_hex else {}),
        )
    return ProxyConfig(
        apps,
        timeout=float(data.get("timeout", 600)),
        ner_model=data.get("ner_model", DEFAULT_MODEL),
        ner_threshold=float(data.get("ner_threshold", 0.5)),
    )


def _required(raw: dict[str, Any], field_name: str, app: str) -> str:
    value = raw.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"app {app!r}: {field_name} is required")
    return value.strip()


def _check_preset(preset: str, app: str) -> None:
    if preset not in PRESETS:
        raise ConfigError(f"app {app!r}: unknown preset {preset!r} (choose from {', '.join(PRESETS)})")


def _upstream_key_env(raw: dict[str, Any], app: str) -> str | None:
    """A config file is checked up front: fail at startup, not on the first request."""
    env = raw.get("upstream_api_key_env")
    if env and not os.environ.get(env):
        raise ConfigError(f"app {app!r}: environment variable {env} is not set")
    return env or None
