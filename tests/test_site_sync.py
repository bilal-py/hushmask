"""The project page's demo (site/detect.js) must find exactly what the Python pattern detectors find.

Runs the JS port with Node; skipped where Node isn't installed (CI has it).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hushmask import EntityType, KnownValue, Masker, Policy

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")

SAMPLES = [
    ("strict", ["Lena Hoffmann"], (ROOT / "examples" / "email.txt").read_text(encoding="utf-8")),
    ("finance", ["Lena Hoffmann"], (ROOT / "examples" / "statement.txt").read_text(encoding="utf-8")),
    ("strict", ["Jonas Becker"], "Von: Jonas Becker <jonas.becker@example.com>\nTelefon: +49 170 9876543\n"
     "Karte 5555 5555 5555 4444, Lieferadresse Lindenallee 7, 50667 Köln. Kollegin Mia Schulz."),
    ("strict", ["Elena Rossi"], "I'm Elena Rossi, reach me at elena.rossi@example.it or +39 347 1234567. "
     "References: Dr. Thomas Klein (thomas.klein@example.de)."),
    ("strict", [], "Ship to 1600 Pennsylvania Ave NW, Washington, DC 20500 or 42 Wallaby Way, Sydney NSW 2000. "
     "UK office: 10 Downing Street, London SW1A 2AA. Paris: 12 rue de Rivoli, 75001 Paris. Via Roma 10."),
    ("strict", [], "Kontonummer: 0532013000, IBAN DE89 3704 0044 0532 0130 00, call (776) 5008567 or 0296 69224164. "
     "anna.müller@web.de paid via PayPal 10.99 on 01.02.2026 1030. Spring 2026, Platz 2, REWE BERLIN 45.20 Dr"),
    ("finance", [], "IFSC HDFC0001234, PAN ABCPE1234F, UPI rahul.sharma@okhdfcbank, IP 192.168.1.20, "
     "card 4111-1111-1111-1111, A/c No. XXXXXXXX1234"),
]  # fmt: skip


def python_spans(preset: str, known: list[str], text: str) -> list[list]:
    masker = Masker(policy=Policy.preset(preset), known=[KnownValue(k, EntityType.PERSON) for k in known])
    return [[str(e.type), e.start, e.end] for e in masker.detect(text, use_models=False)]


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_site_demo_matches_python_detectors():
    script = (
        "const {detect} = require(process.argv[1]);"
        "const samples = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "console.log(JSON.stringify(samples.map(([p, k, t]) => detect(t, p, k).map(e => [e.type, e.start, e.end]))));"
    )
    result = subprocess.run(
        [NODE, "-e", script, str(ROOT / "site" / "detect.js")],
        input=json.dumps(SAMPLES),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    js = json.loads(result.stdout)
    for (preset, known, text), js_spans in zip(SAMPLES, js, strict=True):
        py_spans = python_spans(preset, known, text)
        if js_spans != py_spans:
            only_py = [(t, text[s:e]) for t, s, e in py_spans if [t, s, e] not in js_spans]
            only_js = [(t, text[s:e]) for t, s, e in js_spans if [t, s, e] not in py_spans]
            pytest.fail(f"site/detect.js disagrees with Python.\nonly Python: {only_py}\nonly JS: {only_js}")
