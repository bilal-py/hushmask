# hushmask: plan

## Vision

One local privacy layer with the same rules everywhere: your apps (through an OpenAI-compatible proxy) and,
later, your browser chats (through an extension). It hides personal data before text reaches an AI and puts it
back after, managed from one dashboard, with published numbers on how much it catches and how much it costs
the AI in accuracy.

It's a portfolio and learning project first, and the privacy layer for Spence second. Not a business on its own:
Presidio, LLM Guard, Private AI and others already cover parts of this.

## How it stands out

1. **The full round trip.** Mask → AI → restore, with a check that every token came back.
2. **JSON-aware restore** for structured output.
3. **Same token for the same value**, across calls and across formats (`+91 98765 43210` = `09876543210`).
4. **Task-aware presets.** Finance keeps merchants and amounts; generic tools mask organisations and break categorization.
5. **Indian and EU formats:** Aadhaar, PAN, UPI, IFSC, IBAN, and more to come (GSTIN, German tax ID, BSN…).
6. **Privacy vs usefulness report.** For each preset: how much PII leaked, and how much the AI's task accuracy dropped.

## Phases

| # | Scope | Status |
|---|---|---|
| 0 | Core library: pattern + checksum detectors, known values, HMAC tokens, vault, mask/restore/restore_json, fail-closed guard, CLI, tests | **done** |
| 1 | Model-based names/places (GLiNER, local CPU); same token for name variants ("Rahul Sharma" / "Mr Sharma") | **done** |
| 2 | FastAPI proxy compatible with the OpenAI API (no streaming first); per-app API keys → per-app policy | next |
| 3 | Web dashboard + playground (React): paste text, see what the AI receives, manage apps and presets | |
| 4 | Evaluation: ai4privacy datasets + own statement samples; leak rate per type; task accuracy with/without masking | |
| 5 | Spence integration (point its base URL at the proxy) | |
| 6 | Files (PDF → DOCX → images with local OCR), streaming, realistic fake values, browser extension | later |

## Known gaps

- Third-party names are only caught with `--ner`, and only as well as the model does. No measured leak rate yet (phase 4).
- Name linking only works shorter → longer and only if the full name was seen first (in this or an earlier call) or is
  a known value. "Mr Sharma" in one call and "Rahul Sharma" in a later call stay unlinked.
- A lone initial ("R.") is not detected, so "R. Sharma" masks only "Sharma".
- Restore keeps the first form seen of a value ("RAHUL SHARMA" and "Rahul Sharma" restore to whichever came first).
- The model is ~1 GB plus ~700 MB of PyTorch. An ONNX build would cut that a lot (later).
- The model doesn't take part in the leak guard, so a name it found once but misses on re-scan isn't flagged.
- Tokens glued to another word with `_` (`ref_PERSON_ab12cd`) aren't restored.
- A 10-digit number starting 6–9 is treated as an Indian mobile, even if it's an order number.
- Known values of 3 characters (e.g. "Ram") will also mask the ordinary word.

## Decision log

| Date | Decision | Why |
|---|---|---|
| 2026-11-22 | Name: hushmask | `veil` is taken (lemonadesaltbagel/veil, a privacy proxy for coding agents) |
| 2026-11-22 | Python, separate repo from Spence | Detection ecosystem (Presidio, GLiNER, spaCy, OCR) is Python; Spence stays .NET and talks to the proxy |
| 2026-11-22 | Developer tool (library + proxy + dashboard), not a consumer app | End users meet it through apps; the proxy makes any OpenAI-compatible app work with a base-URL change |
| 2026-11-22 | Tokens `TYPE_<hmac6>`, deterministic per session secret | Same value → same token; stable prompts keep provider caching working (idea from lemonadesaltbagel/veil) |
| 2026-11-22 | Fail closed: re-scan masked text, raise `LeakError` | Sending raw data is worse than failing the request |
| 2026-11-22 | Overlaps: longest span wins, priority breaks ties | A known name inside an email must mask the whole email, not split it and leak the domain |
| 2026-11-22 | Known values always masked, regardless of preset | If the user listed it, they want it hidden |
| 2026-11-22 | Text only first; no extension yet | Get detection and restore right before adding formats and surfaces |
| 2026-11-22 | MIT licence | Portfolio project; simplest permissive licence |
| 2026-11-22 | NER model `urchade/gliner_multi_pii-v1` | Compared with `knowledgator/gliner-pii-base-v1.0` and `nvidia/gliner-PII` on statement lines + prose: best recall on names, 7 s load vs ~110 s |
| 2026-11-22 | Model reads a same-length view (separators → spaces, upper-case lines title-cased) | On ALL-CAPS statements the model missed third-party names; with the view it caught 8/8 in our sample. Same length keeps offsets exact |
| 2026-11-22 | No "organization" label by default; finance preset skips LOCATION | Organisations on statements are merchants, and cities sit inside merchant names; masking them breaks categorization |
| 2026-11-22 | Leak guard uses deterministic detectors only | A model can flag something new on re-scan just because context changed; that must not fail requests at random |
| 2026-11-22 | Name variants: `PERSON_<base>_<n>` | Links "Mr Sharma" to "Rahul Sharma" for the AI while restoring each to the exact text; ambiguous surnames don't link |
| 2026-11-22 | gliner + protobuf behind the optional `ner` extra | Core stays dependency-free; the model stack is ~1.7 GB |
