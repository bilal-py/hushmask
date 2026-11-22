# hushmask

[![CI](https://github.com/bilal-py/hushmask/actions/workflows/ci.yml/badge.svg)](https://github.com/bilal-py/hushmask/actions/workflows/ci.yml)
· [Project page](https://bilal-py.github.io/hushmask/)

Hide personal data before text goes to an AI, and put the real values back in the answer. Runs on your machine.

```
please send the contract to Lena Hoffmann      please send the contract to PERSON_0f24a5
(lena.hoffmann@example.de, +49 151 23456789)  ─▶ (EMAIL_75333f, PHONE_311bb1)
The deposit goes to DE89 3704 0044 0532 0130 00  The deposit goes to IBAN_b55883
```

The AI still understands the request; it just never learns who is involved. Any app that talks to an
OpenAI-style API can use it by changing one URL.

> **Status: early.** Text only. See [docs/PLAN.md](docs/PLAN.md) for the roadmap, known gaps and ideas.

## Quick start

```powershell
git clone https://github.com/bilal-py/hushmask && cd hushmask
.\setup.ps1                     # macOS/Linux: ./setup.sh   (add -Names / --names for the names model)
uv run hushmask serve --open    # opens the dashboard at http://127.0.0.1:8700/dashboard/
```

The setup script installs [uv](https://docs.astral.sh/uv/) if needed, the Python package, and builds the
dashboard (needs Node 20+; without Node you still get the proxy and CLI). Then, in the dashboard:

1. **Playground:** paste any text and see what an AI would receive.
2. **Apps → Add app:** pick a provider (Ollama for fully local, or OpenAI / Gemini / OpenRouter / Groq), then
   copy the base URL and key it shows into your app.
3. **Playground → Send it to an AI:** run a real request through that app and see each stage.

Just want to try it on a file, no server:

```bash
uv run hushmask mask examples/email.txt --known "PERSON=Lena Hoffmann"
uv run hushmask mask examples/email.txt --known "PERSON=Lena Hoffmann" --ner   # also names nobody listed
```

## How well it works

Share of personal values **fully** hidden on labelled data ([tables](docs/eval/RESULTS.md),
[method](docs/eval/README.md)):

| Data | Patterns | + your list | + names model | Over-masking (best setup) |
|---|---:|---:|---:|---|
| ai4privacy English (500 everyday texts) | 26.5% | n/a | **87.0%** | 200 ordinary words |
| ai4privacy German (300 everyday texts) | 25.6% | n/a | **90.0%** | 106 ordinary words |
| Synthetic bank statements (300) | 50.6% | 73.0% | **99.4%** | none; 0 of 1,396 merchants touched |

ai4privacy is the honest number; the synthetic statements were written by this project and flatter it. Most
leaks are random-digit "card numbers" that fail the card checksum (left alone on purpose) and street addresses.
Usernames, passwords, dates of birth and ID numbers aren't detected; they're reported separately.

## What it hides

| Kind | How |
|---|---|
| Your own values (name, address, IDs) | your "always hide" list: whole words, any case |
| Other people's names, street addresses, cities | local names model (GLiNER, optional, ~1.7 GB) |
| Email, phone (international and national formats) | patterns |
| Card numbers, IBAN | checksums (Luhn, mod 97) |
| Account numbers | next to "Account No." and similar |
| Indian IDs: Aadhaar, PAN, IFSC, UPI | checksums and formats |

Presets: **strict** hides everything above; **finance** keeps cities and bank codes so an AI can still
categorize spending. Same value, same token, every time; "Mr Becker" links to "Jonas Becker" as
`PERSON_<id>_1` so the AI knows it's the same person.

## Use it as a proxy

```bash
uv run hushmask serve                                    # apps managed in the dashboard (~/.hushmask/apps.json)
uv run hushmask serve --upstream http://localhost:11434/v1 --known "PERSON=Lena Hoffmann"   # one provider, no setup
uv run hushmask serve --config hushmask.toml             # apps from a file, see hushmask.example.toml
```

In your app: base URL `http://127.0.0.1:8700/v1`, API key = the app's hushmask key (or, with `--upstream`,
your provider key, which is forwarded).

- Masks every message (system, user, history, tool calls and results) and restores the answer, including JSON.
- Refuses images, audio and files unless an app allows them (they can't be masked).
- Waits for the whole answer before replying (a token split across stream chunks can't be restored); clients
  asking for a stream still work.
- Counts only, never values, in `GET /hushmask/stats` and the dashboard.

## Use it from Python

```python
from hushmask import EntityType, GlinerDetector, KnownValue, Masker, Policy

masker = Masker(
    policy=Policy.preset("strict"),
    known=[KnownValue("Lena Hoffmann", EntityType.PERSON)],
    extra_detectors=[GlinerDetector()],  # optional, needs the 'ner' extra
)
masked = masker.mask(text)  # send masked.text to the AI
print(masker.restore(ai_answer).text)  # real values back
data, info = masker.restore_json(parsed_json)  # structured output
```

## Safety rules

- **Fails closed:** masked text is scanned again; if anything detectable survived, it's refused, not sent.
- **Real values stay in memory** for the request. The CLI writes a vault file only if you pass `--vault`.
- **Dashboard is local only:** answers on localhost with a header other websites can't add.
- **Not anonymization:** what's left (dates, amounts, places) can still say a lot in combination.

## Development

```bash
uv sync --extra proxy --extra ner
uv run pytest && uv run ruff check . && uv run ruff format --check .
cd web && npm run dev            # dashboard with hot reload, talks to a running `hushmask serve`
uv run hushmask eval detect      # see docs/eval/README.md
```

CI runs tests, lint and the dashboard build on every push; pushes to `main` publish `site/` to GitHub Pages;
tags `v*` attach a ready-to-install wheel (dashboard included) to a GitHub release.
