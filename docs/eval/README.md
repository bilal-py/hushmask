# How hushmask is evaluated

Numbers live in [RESULTS.md](RESULTS.md); this page says what they mean and where they mislead.

## Three questions

1. **How much leaks?** On labelled text, is every character of every personal value hidden?
2. **How much is over-masked?** Does hushmask hide things that aren't personal, especially the merchants an AI
   needs to categorize spending?
3. **What does masking cost the AI?** Does a real model categorize transactions as well when it only sees tokens?

## Scoring

- A labelled value is **protected** if every non-space character is inside a masked span, **partly visible** if
  some are, and **leaked** if none are. Partly visible counts as a leak: half a card number or a surname is still out.
- The type doesn't have to match. A name masked as `CUSTOM` is still hidden, and hiding is what matters.
- **Over-masked spans** are masked spans that touch no labelled value at all.
- **Merchants damaged** (synthetic data only) counts merchant names that were partly or fully masked.
- Values of a kind the preset keeps on purpose (cities in the finance preset) and kinds hushmask doesn't claim to
  find (usernames, passwords, US social security numbers…) are listed separately, not mixed into the leak rate.

## Datasets

**Synthetic bank statements** (`hushmask eval detect`): a seeded generator
([`synthetic.py`](../../src/hushmask/evaluation/synthetic.py)) writes statements in Indian and European formats:
holder, account or IBAN, IFSC, address, PAN and Aadhaar, card and UPI payments, transfers to people, a footer with
email and phone, sometimes a free-text note naming a friend and a city. Every value is labelled, every merchant is
marked "keep", and every transaction has its true category.

> **Bias:** the same person wrote these formats and the detectors, so this set flatters the pattern detectors.
> Treat it as a regression test for statements, not as proof.

**ai4privacy `pii-masking-400k`** (`--dataset ai4privacy`): random records from the validation split of
[ai4privacy/pii-masking-400k](https://huggingface.co/datasets/ai4privacy/pii-masking-400k), in English and German.
Mostly short emails, forms and letters, not bank statements. It's downloaded on first use to
`~/.cache/hushmask/` and never committed: its licence allows academic, non-commercial use only and forbids
redistribution. Credit: Ai4Privacy. Its card numbers are random digits that usually fail the Luhn checksum,
which hushmask treats as "not a card"; that shows up as card leaks.

## Setups compared

| Setup | What's on |
|---|---|
| patterns | regexes and checksums only |
| + your list | plus the values a user would list: the account holder's name and address (synthetic only) |
| + names model | plus GLiNER (`urchade/gliner_multi_pii-v1`, threshold 0.5) for names, addresses and places |

## AI accuracy

`hushmask eval task` sends each synthetic statement to an OpenAI-compatible model twice, at temperature 0 with a
JSON schema: once as it is, once through hushmask (finance preset, holder listed, names model if `--ner`). It
compares the categories with the truth and checks that people's names came back restored. CPU models are slow,
so this runs on a handful of statements. It's an indication, not a benchmark.

## Re-running

```bash
uv sync --extra ner --extra proxy
uv run hushmask eval detect --dataset synthetic --n 300 --ner
uv run hushmask eval detect --dataset ai4privacy --language en --n 500 --ner
uv run hushmask eval detect --dataset ai4privacy --language de --n 300 --ner
uv run hushmask eval task --upstream http://localhost:11434/v1 --model qwen2.5:7b --n 8 --ner
```

Each command writes a JSON file here and rebuilds `RESULTS.md`. Runs are seeded (`--seed`, default 7).
