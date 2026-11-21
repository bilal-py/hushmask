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
    return Masker(policy=Policy.preset(args.preset), known=_known(args))


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
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
