# hushmask

Hide personal data before text goes to an AI, and put the real values back after.

```
your text ──▶ detect PII ──▶ swap for tokens ──▶ AI ──▶ swap tokens back ──▶ result
                                   │                           ▲
                                   └── vault (in memory only) ─┘
```

```
Statement for Rahul Sharma            Statement for PERSON_8b2b69
UPI/rahul.sharma@okhdfcbank/SWIGGY ─▶ UPI/UPI_29353b/SWIGGY
POS 4111 1111 1111 1111 AMAZON PAY    POS CARD_3ef187 AMAZON PAY
```

Merchants, amounts and dates stay, so the AI can still do its job (categorize, summarize, extract).

> **Status: early.** Text only, pattern- and list-based detection. Names the tool hasn't been told about
> (e.g. a third party in "NEFT FROM PRIYA MEHTA") are **not** caught yet; that needs the model-based
> detector in phase 1. See [docs/PLAN.md](docs/PLAN.md).

## Try it

```bash
uv sync
uv run hushmask detect examples/statement.txt --known "PERSON=Rahul Sharma"
uv run hushmask mask examples/statement.txt --known "PERSON=Rahul Sharma" --vault vault.json > masked.txt
uv run hushmask restore masked.txt --vault vault.json
```

The vault file holds the real values. Delete it when you're done.

## Use it from Python

```python
from hushmask import EntityType, KnownValue, Masker, Policy

masker = Masker(policy=Policy.preset("finance"), known=[KnownValue("Rahul Sharma", EntityType.PERSON)])

masked = masker.mask(statement_text)  # masked.text goes to the AI
answer = call_your_llm(masked.text)
print(masker.restore(answer).text)  # real values back

data, info = masker.restore_json(parsed_json)  # structured output: restores every string
```

One `Masker` is one session: the same value always gets the same token, and the vault grows as you mask more.

## What it detects

| Type | How | Checked |
|---|---|---|
| Your own values (name, address, IDs) | `--known` list, whole words, case/space-insensitive | exact |
| Card | 13–19 digits | Luhn |
| IBAN | country + check digits | mod 97 |
| Aadhaar | 12 digits | Verhoeff |
| PAN, IFSC | format | pattern |
| Account number | next to "A/c", "Account No." | context |
| Email, UPI ID, phone, IPv4 | format | pattern |

## Safety rules

- **Fail closed.** After masking, the text is scanned again. If anything detectable is still visible, `mask()`
  raises `LeakError` (which never contains the values) instead of returning text.
- **Vault in memory.** Nothing is written to disk unless you ask the CLI to (`--vault`).
- **Not anonymization.** Merchants, amounts, dates and places can still identify someone in combination.
  This hides *who you are* from the AI provider; it doesn't make data anonymous.

## Development

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
