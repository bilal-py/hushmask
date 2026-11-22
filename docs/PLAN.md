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
| 2 | FastAPI proxy compatible with the OpenAI API (no streaming first); per-app API keys → per-app policy | **done** |
| 3 | Web dashboard + playground (React): paste text, see what the AI receives, manage apps and presets | **done** |
| 4 | Evaluation: ai4privacy datasets + own statement samples; leak rate per type; task accuracy with/without masking | **done** (detection); AI-accuracy run pending |
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
- Proxy: no real streaming (whole answer arrives at once), only chat completions (no `/v1/responses`, no
  Anthropic API), apps live in a TOML file (no UI yet), stats are in memory and reset on restart.
- Proxy: names in system prompts are only caught if they're known values (model detection is off there).
- Proxy: JSON content is re-serialized after restore, so its whitespace/formatting changes.
- Dashboard: the build output isn't committed, so a fresh clone needs `npm run build` in `web/` before the
  dashboard appears (the proxy works without it). Packaging the build into the wheel comes with a release.
- Dashboard: provider keys "saved in the apps file" are plain text in `~/.hushmask/apps.json`; an environment
  variable is the safer option and the default. OS keychain storage would be better (later).
- Dashboard: stats are in memory and reset on restart; there's no request history.
- Dashboard: hovering works from the AI's view to the source text, not the other way (the textarea sits on top).
- Eval: the AI-accuracy run (`hushmask eval task`) hasn't completed yet. With the names model and a 7B Ollama
  model loaded together, the machine ran out of memory at statement 3 of 8.
- Eval: on ai4privacy the names model masks ~0.4 ordinary capitalized words per record ("Volunteer", "Hallo").
  A higher threshold for single-word names might help; measure before changing.
- Eval: street addresses leak about half the time on English ai4privacy (18/37 protected).
- Site: the in-browser demo is a JavaScript port of the pattern rules (no names model, FNV hash instead of HMAC).
  Keep it in sync when detectors change.
- Tokens glued to another word with `_` (`ref_PERSON_ab12cd`) aren't restored.
- A 10-digit number starting 6–9 is treated as an Indian mobile, even if it's an order number.
- Known values of 3 characters (e.g. "Ram") will also mask the ordinary word.

## What's left

1. Re-run the AI-accuracy eval (`hushmask eval task`); it ran out of memory with the names model and a 7B model loaded together.
2. Phase 5: point Spence at the proxy (needs a "custom base URL" setting in Spence's AI settings).
3. Tag `v0.1.0` so the release workflow publishes an installable wheel.
4. Phase 6 items (files, streaming, fake values, browser extension), in that order of value.

## Improvement ideas (keep all current behaviour)

Ordered by value for effort. None of these remove a feature.

- **Smaller, faster names model:** export GLiNER to ONNX and run it with onnxruntime. Likely cuts the ~1.7 GB
  install to a few hundred MB and halves CPU time, and fixes the out-of-memory run. Keep PyTorch as a fallback.
- **One-line install:** publish to PyPI (`uv tool install hushmask[proxy]`) with the dashboard in the wheel, and
  a Docker image (`docker run -p 8700:8700 hushmask`). The release workflow already builds the wheel.
- **Fewer false names:** require a higher score (~0.75) for single-word names, and skip capitalized words at the
  start of a line/sentence that the model only scores weakly ("Hallo", "Volunteer"). Measure with
  `hushmask eval detect --dataset ai4privacy --ner` before keeping it.
- **Address patterns:** German/EU street formats ("Bergstraße 12, 10115 Berlin", "Rue de Rivoli 5") as a
  pattern, so addresses don't depend on the model. Addresses are the biggest remaining leak on English text.
- **More EU identifiers with checksums:** German tax ID (Steuer-ID), Dutch BSN, French INSEE, Spanish DNI/NIE,
  passport numbers. Same approach as IBAN: pattern + checksum, so no over-masking.
- **Case-insensitive `ß`:** "WEISS" doesn't match a listed "Weiß" (Python's IGNORECASE doesn't map ß↔SS).
  Normalise both sides before matching.
- **Real streaming:** stream from upstream and hold back only text that could be the start of a token
  (`[A-Z]+_[0-9a-f]*`), releasing everything else immediately. Keeps restore safe, cuts waiting time.
- **More APIs:** OpenAI `/v1/responses`, `/v1/embeddings` (mask only), and Anthropic's `/v1/messages`, so more
  tools can sit behind hushmask.
- **Provider keys in the OS keychain** (Windows Credential Manager, macOS Keychain) instead of plain text in
  `apps.json`; environment variables stay supported.
- **Persistent counts:** keep per-app stats (counts only) in a small SQLite file with a daily chart in the
  dashboard, so they survive restarts.
- **Dashboard:** hover from source text to token too (render the editor's marks as hit targets), and a
  "copy masked text" button for people who paste into chat UIs by hand.
- **Request limits:** a max body size and a per-app rate limit, so a runaway client can't exhaust memory.
- **Site demo in sync with Python:** a CI test that runs the same sample texts through the JS port and the Python
  detectors and fails if they disagree.

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
| 2026-11-22 | Proxy: two modes, passthrough (`--upstream`, client key forwarded) and apps (`hushmask.toml`, per-app key/upstream/rules) | One command to try it; per-app rules when several apps share it, with provider keys kept out of apps |
| 2026-11-22 | Proxy: always call upstream non-streaming; fake-stream SSE back if asked | A token split across chunks can't be restored; buffered SSE keeps streaming clients working |
| 2026-11-22 | Proxy: per-app fixed token secret | History is re-masked every turn; same tokens keep the conversation consistent and the prompt cache warm |
| 2026-11-22 | Proxy: refuse images/audio/files unless `allow_images` | They can't be masked; sending them silently would defeat the point |
| 2026-11-22 | Proxy: system/developer messages skip model detection | Real run: GLiNER tagged "the person or merchant" as a name, which garbled the instruction and the result |
| 2026-11-22 | NER: drop spans containing a label word | Same bug from the model side; real names don't contain "person"/"city"/"address" |
| 2026-11-22 | Proxy binds 127.0.0.1 by default, warns otherwise | Passthrough mode has no auth of its own |
| 2026-11-22 | `hushmask serve` with no flags = apps managed in the dashboard, saved to `~/.hushmask/apps.json` with each app's token secret | Easiest start; persisted secrets keep tokens stable across restarts. TOML stays as a read-only option |
| 2026-11-22 | Provider key: env var name (default) or stored in the apps file; read at request time | Env var keeps secrets off disk; reading late means setting it after startup works |
| 2026-11-22 | Dashboard API guarded by localhost Host check + `X-Hushmask-Admin` header | Blocks DNS rebinding and cross-site requests (custom header forces a CORS preflight we never approve) without login screens for a local tool |
| 2026-11-22 | Names model loads lazily on first use | Apps and the playground can turn it on at runtime; no 7 s startup for people who don't use it |
| 2026-11-22 | Dashboard: React + Vite + Tailwind 4, built into `src/hushmask/web_dist`, served at `/dashboard/` | Same stack as Spence; one process serves proxy and UI |
| 2026-11-22 | Dashboard look: highlighter pens for found values, redaction tape for tokens; Schibsted Grotesk + IBM Plex Mono (document text only); light + dark | The subject is marking up a document before redaction. In dark mode marks are a translucent wash + underline so the textarea's light text stays readable |
| 2026-11-22 | Phone pattern: brackets only as a pair | The dashboard showed `(…, +91 98765 43210)` losing its `)` in the masked text |
| 2026-11-22 | Evaluation = synthetic statements (seeded, exact labels, merchants marked "keep", true categories) + ai4privacy validation (en, de) | Synthetic is biased towards our formats but measures over-masking and AI accuracy; ai4privacy is outside data for honesty |
| 2026-11-22 | Score by characters hidden, not by type; partly visible counts as a leak | Privacy is about what the provider can read; half a surname is still out |
| 2026-11-22 | ai4privacy downloaded at run time to ~/.cache, never committed; only aggregates published | Its licence is academic/non-commercial with no redistribution |
| 2026-11-22 | Email pattern accepts any letters (`\w`), not just ASCII | First eval run: every synthetic email leak was a `müller@…` address |
| 2026-11-22 | Added a loose national phone pattern (trunk 0 or bracketed area code, 9–14 digits, dates rejected) | ai4privacy phone leaks 17 → 3 (en) and 11 → 3 (de) with zero new over-masking on statements |
| 2026-11-22 | Names model: drop spans with fewer than 2 letters | First eval run showed single letters ("M") masked as people |
| 2026-11-22 | Cards stay Luhn-checked even though ai4privacy's random card numbers then leak | Matching any 16-digit run would mask account numbers and references; real cards pass Luhn |
| 2026-11-22 | Examples, dashboard sample and site use European (German) names and general texts, not Indian/payment-only | hushmask is a general tool, independent of Spence; target audience is Europe |
| 2026-11-22 | Known-values pattern built from values as written, lookups casefolded | German example exposed it: casefold("ß") == "ss" made "Bergstraße" unmatchable |
| 2026-11-22 | Account detector also reads German labels (Kontonummer, Konto-Nr.) | German examples and users |
| 2026-11-22 | Site: EN/DE and light/dark switches, language from the browser, both remembered | European audience; follows the dashboard's design |
| 2026-11-22 | CI: tests + lint on Ubuntu and Windows (Python 3.12/3.13), dashboard build; Pages deploys `site/`; tags `v*` publish a wheel with the dashboard | Easy install without Node for testers; names model left out of CI (tests use a fake model) |
| 2026-11-22 | `setup.ps1` / `setup.sh` + `hushmask serve --open` | One command to install, one to run |
