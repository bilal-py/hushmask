# CLAUDE.md

hushmask hides PII before text goes to an AI and restores it after. **Read `docs/PLAN.md` first** (vision, phases,
known gaps, decision log). Append to the decision log whenever a design decision is made.

## Commands

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .
uv run hushmask --help

# model-based detection (optional extra; ~1.7 GB with the model)
uv sync --extra ner
HUSHMASK_MODEL_TESTS=1 uv run --extra ner pytest -k real

# proxy + dashboard (http://127.0.0.1:8700/dashboard/)
uv run --extra proxy hushmask serve                            # apps in ~/.hushmask/apps.json, editable
uv run --extra proxy hushmask serve --upstream http://localhost:11434/v1 --preset finance
uv run --extra proxy hushmask serve --config hushmask.toml     # read-only, see hushmask.example.toml

# dashboard (web/), React 19 + TS + Vite + Tailwind 4
cd web && npm install
npm run dev      # http://localhost:5173/dashboard/, proxies API calls to a running hushmask serve
npm run build    # → src/hushmask/web_dist (git-ignored), served by hushmask serve
npm run lint
```

## Layout (`src/hushmask/`)

- `entities.py`: `EntityType`, `Entity` (span + detector + priority).
- `validators.py`: Luhn, IBAN mod 97, Aadhaar Verhoeff, digit counts, IPv4.
- `detectors.py`: `Detector` protocol, `PatternDetector` (regex + optional validator + capture group),
  `KnownValuesDetector` (user-supplied values; PERSON parts ≥3 chars also match alone), `default_detectors()`.
- `policy.py`: `Policy` = set of enabled types; `PRESETS` (strict, finance). Known values ignore the policy.
- `ner.py`: `GlinerDetector` (lazy-loads GLiNER; `deterministic = False`). `model_view` (same-length copy:
  separators → spaces, upper-case lines title-cased), `chunks` (line-based, keeps offsets), `trim_span`
  (drops NEFT/IMPS/… from span edges). Accepts any object with `predict_entities` (tests use a fake).
- `masker.py`: `Masker` = one session (secret + vault). `detect` → resolve overlaps (longest, then priority) →
  `mask` (HMAC tokens `TYPE_<6 hex>`, lengthened on collision; PERSON variants `PERSON_<base>_<n>`, full names
  assigned first) → `_guard` (deterministic detectors only; fail closed with `LeakError`).
  `restore` / `restore_json` are case-tolerant and report unknown tokens.
- `cli.py`: `detect`, `mask`, `restore`, `serve`.
- `proxy/` (optional `proxy` extra; FastAPI + httpx + uvicorn):
  - `config.py`: `AppConfig`, `ProxyConfig`, `load_config` (TOML), `passthrough_config`.
  - `openai.py`: pure functions. `mask_request` (all message fields; system/developer skip models; adds the
    placeholder note), `restore_response` (JSON value by value), `to_sse` (buffered stream), `error_body`.
  - `store.py`: `AppStore` (apps + token secrets in JSON, atomic writes; read-only when built from TOML).
  - `server.py`: `create_app(config, store=, transport=)`; `Runtime` (store, `NerHolder` lazy shared model,
    stats); `forward_chat` (mask → upstream → restore, shared by `/v1/chat/completions` and the dashboard).
    Tests inject `httpx.MockTransport`.
  - `admin.py`: `/hushmask/api/*` for the dashboard (info, preview, roundtrip, apps CRUD, rotate key). Every
    route goes through `admin_guard` (localhost Host + `X-Hushmask-Admin: 1`); keep it that way. Never return
    a stored provider key to the browser.
- `web/src/`: `api.ts` (typed client, mirrors `admin.py`; keep in sync), `entities.ts` (type → name and
  highlighter colour), `ui.tsx` + `lib.ts`, `Playground.tsx` + `HighlightEditor.tsx` (transparent textarea over a
  mark layer; both use `.doc` metrics, so change them together), `RoundTrip.tsx`, `Apps.tsx` + `AppForm.tsx`.
  Design tokens live in `index.css`: paper/ink/tape plus `--hl-*` highlighter colours, light and dark.

## Rules

- Never put PII values in exceptions, logs or test failure messages from library code.
- The vault stays in memory; only the CLI writes it, and only with `--vault`.
- New detectors: add a validator where a checksum exists, a test that it fires, and a test that ordinary
  statement text (merchants, amounts, dates) does not trigger it.
- Keep the core free of runtime dependencies; heavy detectors (GLiNER) go behind an optional extra and are
  imported lazily, so `import hushmask` works without them.
- Unit tests never load a real model; real-model tests are skipped unless `HUSHMASK_MODEL_TESTS=1`.
