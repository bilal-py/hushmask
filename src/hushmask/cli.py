"""hushmask command line.

hushmask detect statement.txt
hushmask mask statement.txt --known "PERSON=Lena Hoffmann" --vault vault.json > masked.txt
hushmask restore answer.txt --vault vault.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .detectors import KnownValue
from .masker import LeakError, Masker
from .ner import DEFAULT_MODEL, GlinerDetector
from .policy import PRESETS, Policy

DEFAULT_STORE = Path.home() / ".hushmask" / "apps.json"  # same as proxy.store.DEFAULT_STORE, without importing it


def _read(source: str) -> str:
    # utf-8-sig drops the BOM that Windows tools (PowerShell, Notepad) often add.
    return sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8-sig")


def _known(args: argparse.Namespace) -> list[KnownValue]:
    specs = list(args.known or [])
    if args.known_file:
        specs += [line for line in Path(args.known_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    return [KnownValue.parse(s) for s in specs]


def _masker(args: argparse.Namespace) -> Masker:
    extra = []
    if args.ner:
        print(f"[hushmask] loading {args.ner_model} (first run downloads it)...", file=sys.stderr)
        detector = GlinerDetector(args.ner_model, threshold=args.ner_threshold)
        _ = detector.model
        extra.append(detector)
    return Masker(policy=Policy.preset(args.preset), known=_known(args), extra_detectors=extra)


def cmd_detect(args: argparse.Namespace) -> int:
    for e in _masker(args).detect(_read(args.file)):
        print(f"{e.start:>6}-{e.end:<6} {e.type:<8} {e.detector:<16} {e.text}")
    return 0


def cmd_mask(args: argparse.Namespace) -> int:
    masker = _masker(args)
    try:
        result = masker.mask(_read(args.file))
    except LeakError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    sys.stdout.write(result.text)
    if args.vault:
        Path(args.vault).write_text(json.dumps(dict(masker.vault), indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"\n[hushmask] vault written to {args.vault}. It holds the real values; delete it when done.",
            file=sys.stderr,
        )
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    vault: dict[str, str] = json.loads(Path(args.vault).read_text(encoding="utf-8"))
    masker = Masker()
    masker.load_vault(vault)
    result = masker.restore(_read(args.file))
    sys.stdout.write(result.text)
    if result.unknown:
        print(f"\n[hushmask] unknown tokens left as-is: {', '.join(sorted(result.unknown))}", file=sys.stderr)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn

        from .proxy.config import ConfigError, ProxyConfig, load_config, passthrough_config
        from .proxy.server import create_app
        from .proxy.store import AppStore
    except ImportError:
        print("error: the proxy needs the 'proxy' extra: uv sync --extra proxy", file=sys.stderr)
        return 1
    store = None
    try:
        if args.config:
            config = load_config(args.config)
        elif args.upstream:
            config = passthrough_config(
                args.upstream,
                preset=args.preset,
                known=tuple(_known(args)),
                ner=args.ner,
                allow_images=args.allow_images,
                ner_model=args.ner_model,
                ner_threshold=args.ner_threshold,
            )
        else:
            store = AppStore.open(Path(args.store))
            config = ProxyConfig({}, ner_model=args.ner_model, ner_threshold=args.ner_threshold)
    except (ConfigError, OSError, ValueError, KeyError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if config.passthrough:
        mode = f"passthrough to {args.upstream}"
    elif store is not None:
        mode = f"apps from {store.path} ({len(store.all())})"
    else:
        mode = f"apps from {args.config} (read-only)"
    base = f"http://{args.host}:{args.port}"
    print(f"[hushmask] proxy      {base}/v1   ({mode})", file=sys.stderr)
    print(f"[hushmask] dashboard  {base}/dashboard/", file=sys.stderr)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("[hushmask] warning: listening beyond this machine; anyone who can reach it can use it", file=sys.stderr)
    if args.open:
        import threading
        import webbrowser

        threading.Timer(1.5, webbrowser.open, [f"{base}/dashboard/"]).start()
    uvicorn.run(create_app(config, store=store), host=args.host, port=args.port, log_level="warning")
    return 0


def _progress(message: str) -> None:
    print(f"[hushmask eval] {message}", file=sys.stderr)


def _ner_detector(args: argparse.Namespace) -> GlinerDetector | None:
    if not args.ner:
        return None
    _progress(f"loading {args.ner_model}...")
    detector = GlinerDetector(args.ner_model, threshold=args.ner_threshold)
    _ = detector.model
    return detector


def cmd_eval_detect(args: argparse.Namespace) -> int:
    from .evaluation import ai4privacy, detection, synthetic
    from .evaluation.report import write_results

    if args.dataset == "synthetic":
        docs = synthetic.generate(args.n, args.seed)
        preset = args.preset or "finance"
        title = f"Synthetic bank statements ({preset} preset)"
        description = (
            f"{len(docs)} generated statements (seed {args.seed}), 60% Indian and 40% European formats. Your list = "
            "the account holder's name and address, as a real user would enter them."
        )
        stem = f"detect-synthetic-{preset}"
    else:
        _progress(f"loading ai4privacy ({args.language}), downloading on first use...")
        docs = ai4privacy.load(args.language, args.n, args.seed)
        preset = args.preset or "strict"
        title = f"ai4privacy pii-masking-400k, validation, {args.language} ({preset} preset)"
        description = (
            f"{len(docs)} random records (seed {args.seed}) from the "
            "[ai4privacy](https://huggingface.co/datasets/ai4privacy/pii-masking-400k) validation split, used under "
            "its academic, non-commercial licence. Not built around hushmask's formats. Their GIVENNAME/SURNAME count "
            "as PERSON, STREET/BUILDINGNUM as ADDRESS, CITY as LOCATION."
        )
        stem = f"detect-ai4privacy-{args.language}-{preset}"

    setups = detection.evaluate(docs, preset=preset, model=_ner_detector(args), progress=_progress)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run = {"title": title, "description": description, "dataset": args.dataset, "preset": preset, "setups": setups}
    (out / f"{stem}.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, r in setups.items():
        print(f"{name:<40} leak {100 * r['leak_rate']:5.1f}%   over-masked {r['false_positives']:>4}   "
              f"merchants damaged {r['keep_damaged']}/{r['keep_total']}")  # fmt: skip
    print(f"wrote {write_results(out)}")
    return 0


def cmd_eval_task(args: argparse.Namespace) -> int:
    import os

    from .evaluation import synthetic, task
    from .evaluation.report import write_results

    docs = synthetic.generate(args.n, args.seed)
    api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
    run = task.evaluate(
        docs,
        upstream_url=args.upstream,
        model=args.model,
        api_key=api_key,
        ner=_ner_detector(args),
        progress=_progress,
    )
    run["ner"] = bool(args.ner)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    safe_model = "".join(c if c.isalnum() else "-" for c in args.model)
    (out / f"task-{safe_model}.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, r in run["conditions"].items():
        print(f"{name:<18} category accuracy {100 * r['category_accuracy']:5.1f}%")
    print(f"wrote {write_results(out)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hushmask", description="Hide PII before text goes to an AI, and put it back after."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_input(p: argparse.ArgumentParser) -> None:
        p.add_argument("file", nargs="?", default="-", help="input file, or - for stdin (default)")

    def add_masking(p: argparse.ArgumentParser) -> None:
        p.add_argument("--preset", choices=sorted(PRESETS), default="strict")
        p.add_argument(
            "--known", action="append", metavar="[TYPE=]VALUE", help='always hide this, e.g. "PERSON=Lena Hoffmann"'
        )
        p.add_argument("--known-file", metavar="PATH", help="one [TYPE=]VALUE per line")
        p.add_argument("--ner", action="store_true", help="also find names/addresses/places with a local model")
        p.add_argument("--ner-model", default=DEFAULT_MODEL, metavar="NAME")
        p.add_argument("--ner-threshold", type=float, default=0.5, metavar="0-1")

    p = sub.add_parser("detect", help="list the PII found")
    add_input(p)
    add_masking(p)
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("mask", help="print text with PII replaced by tokens")
    add_input(p)
    add_masking(p)
    p.add_argument("--vault", metavar="PATH", help="save token -> value map (sensitive) for a later restore")
    p.set_defaults(func=cmd_mask)

    p = sub.add_parser("restore", help="put real values back using a saved vault")
    add_input(p)
    p.add_argument("--vault", metavar="PATH", required=True)
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("serve", help="run the OpenAI-compatible privacy proxy")
    p.add_argument("--config", metavar="PATH", help="read-only apps from a hushmask.toml")
    p.add_argument("--upstream", metavar="URL", help="passthrough: forward to this base URL with the client's key")
    p.add_argument(
        "--store", metavar="PATH", default=str(DEFAULT_STORE), help="apps managed in the dashboard (default mode)"
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8700)
    p.add_argument("--allow-images", action="store_true", help="send images unmasked instead of refusing them")
    p.add_argument("--open", action="store_true", help="open the dashboard in your browser")
    add_masking(p)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("eval", help="measure leaks, over-masking and the cost to AI accuracy")
    eval_sub = p.add_subparsers(dest="eval_command", required=True)

    def add_eval_common(q: argparse.ArgumentParser, n: int) -> None:
        q.add_argument("--n", type=int, default=n, help=f"documents to use (default {n})")
        q.add_argument("--seed", type=int, default=7)
        q.add_argument("--out", default="docs/eval", metavar="DIR")
        q.add_argument("--ner", action="store_true", help="also evaluate with the names model")
        q.add_argument("--ner-model", default=DEFAULT_MODEL, metavar="NAME")
        q.add_argument("--ner-threshold", type=float, default=0.5, metavar="0-1")

    q = eval_sub.add_parser("detect", help="leak rate and over-masking on labelled data")
    q.add_argument("--dataset", choices=["synthetic", "ai4privacy"], default="synthetic")
    q.add_argument("--language", default="en", help="ai4privacy language: en, de, fr, es, it, nl")
    q.add_argument("--preset", choices=sorted(PRESETS), help="default: finance for synthetic, strict for ai4privacy")
    add_eval_common(q, 300)
    q.set_defaults(func=cmd_eval_detect)

    q = eval_sub.add_parser("task", help="AI categorization accuracy with and without masking")
    q.add_argument("--upstream", required=True, metavar="URL", help="OpenAI-compatible base URL, e.g. Ollama")
    q.add_argument("--model", required=True)
    q.add_argument("--api-key-env", metavar="VAR")
    add_eval_common(q, 8)
    q.set_defaults(func=cmd_eval_task)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
