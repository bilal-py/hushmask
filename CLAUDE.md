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
- `cli.py`: `detect`, `mask`, `restore`.

## Rules

- Never put PII values in exceptions, logs or test failure messages from library code.
- The vault stays in memory; only the CLI writes it, and only with `--vault`.
- New detectors: add a validator where a checksum exists, a test that it fires, and a test that ordinary
  statement text (merchants, amounts, dates) does not trigger it.
- Keep the core free of runtime dependencies; heavy detectors (GLiNER) go behind an optional extra and are
  imported lazily, so `import hushmask` works without them.
- Unit tests never load a real model; real-model tests are skipped unless `HUSHMASK_MODEL_TESTS=1`.
