"""hushmask command line.

hushmask detect statement.txt
hushmask mask statement.txt --known "PERSON=Rahul Sharma" --vault vault.json > masked.txt
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

        from .proxy.config import ConfigError, load_config, passthrough_config
        from .proxy.server import create_app
    except ImportError:
        print("error: the proxy needs the 'proxy' extra: uv sync --extra proxy", file=sys.stderr)
        return 1
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
            print("error: give --config hushmask.toml or --upstream URL", file=sys.stderr)
            return 1
    except (ConfigError, OSError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    mode = "passthrough" if config.passthrough else f"apps: {', '.join(config.apps)}"
    print(f"[hushmask] proxy on http://{args.host}:{args.port}/v1 ({mode})", file=sys.stderr)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("[hushmask] warning: listening beyond this machine; anyone who can reach it can use it", file=sys.stderr)
    uvicorn.run(create_app(config), host=args.host, port=args.port, log_level="warning")
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
            "--known", action="append", metavar="[TYPE=]VALUE", help='always hide this, e.g. "PERSON=Rahul Sharma"'
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
    p.add_argument("--config", metavar="PATH", help="hushmask.toml with per-app settings")
    p.add_argument("--upstream", metavar="URL", help="no config: forward to this OpenAI-compatible base URL")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8700)
    p.add_argument("--allow-images", action="store_true", help="send images unmasked instead of refusing them")
    add_masking(p)
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
