# CLAUDE.md

hushmask hides PII before text goes to an AI and restores it after. **Read `docs/PLAN.md` first** (vision, phases,
known gaps, decision log). Append to the decision log whenever a design decision is made.

## Commands

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .
uv run hushmask --help
```

## Layout (`src/hushmask/`)

- `entities.py`: `EntityType`, `Entity` (span + detector + priority).
- `validators.py`: Luhn, IBAN mod 97, Aadhaar Verhoeff, digit counts, IPv4.
- `detectors.py`: `Detector` protocol, `PatternDetector` (regex + optional validator + capture group),
  `KnownValuesDetector` (user-supplied values; PERSON parts ≥3 chars also match alone), `default_detectors()`.
- `policy.py`: `Policy` = set of enabled types; `PRESETS` (strict, finance). Known values ignore the policy.
- `masker.py`: `Masker` = one session (secret + vault). `detect` → resolve overlaps (longest, then priority) →
  `mask` (HMAC tokens `TYPE_<6 hex>`, lengthened on collision) → `_guard` (fail closed with `LeakError`).
  `restore` / `restore_json` are case-tolerant and report unknown tokens.
- `cli.py`: `detect`, `mask`, `restore`.

## Rules

- Never put PII values in exceptions, logs or test failure messages from library code.
- The vault stays in memory; only the CLI writes it, and only with `--vault`.
- New detectors: add a validator where a checksum exists, a test that it fires, and a test that ordinary
  statement text (merchants, amounts, dates) does not trigger it.
- Keep the core free of runtime dependencies; heavy detectors (GLiNER) go behind an optional extra.
