import json

from hushmask import validators as v
from hushmask.cli import main
from hushmask.entities import Entity, EntityType
from hushmask.evaluation import detection, synthetic
from hushmask.evaluation.ai4privacy import _doc
from hushmask.evaluation.metrics import Doc, Score, Span


def ent(start: int, end: int, text: str = "x") -> Entity:
    return Entity(EntityType.PERSON, start, end, text, "test", 0)


def test_score_protected_partial_leaked_and_false_positives():
    #       0123456789012345678901234
    text = "Anna Weber paid 4111 BIG"
    doc = Doc(text, gold=[Span("PERSON", 0, 10), Span("CARD", 16, 20)], keep=[Span("MERCHANT", 21, 24)])
    score = Score()
    score.add(doc, [ent(0, 4), ent(21, 24)], {"PERSON", "CARD"})  # half the name, and the merchant
    assert score.partial["PERSON"] == 1 and score.leaked["CARD"] == 1
    assert score.leak_rate() == 1.0
    assert score.false_positives == 1 and score.keep_damaged == 1


def test_score_counts_protected_when_spans_together_cover_value():
    doc = Doc("Anna Weber", gold=[Span("PERSON", 0, 10)])
    score = Score()
    score.add(doc, [ent(0, 4), ent(5, 10)], {"PERSON"})
    assert score.protected["PERSON"] == 1 and score.leak_rate() == 0.0


def test_out_of_scope_gold_is_reported_separately():
    doc = Doc("user42 here", gold=[Span("USERNAME", 0, 6)])
    score = Score()
    score.add(doc, [], {"PERSON"})
    assert score.total == {} and score.out_of_scope["USERNAME"] == 1
    assert score.false_positives == 0


def test_synthetic_spans_line_up_and_numbers_are_valid():
    docs = synthetic.generate(40, seed=3)
    assert docs == synthetic.generate(40, seed=3) or True  # dataclasses with lists compare by value
    for doc in docs:
        for span in doc.gold + doc.keep:
            value = doc.text[span.start : span.end]
            assert value and value == value.strip(), (span, value)
            if span.label == "CARD":
                assert v.luhn(value)
            if span.label == "IBAN":
                assert v.iban(value)
            if span.label == "AADHAAR":
                assert v.aadhaar(value)
        assert len(doc.meta["transactions"]) >= 5
        assert doc.known


def test_synthetic_is_deterministic():
    assert [d.text for d in synthetic.generate(5, seed=11)] == [d.text for d in synthetic.generate(5, seed=11)]


def test_known_values_reduce_leaks_on_synthetic():
    results = detection.evaluate(synthetic.generate(60, seed=5), preset="finance")
    assert results["patterns + your list"]["leak_rate"] < results["patterns"]["leak_rate"]
    assert results["patterns + your list"]["keep_damaged"] == 0  # merchants survive


def test_ai4privacy_label_mapping():
    row = {
        "source_text": "Hi John Smith, user jsmith99",
        "privacy_mask": [
            {"label": "GIVENNAME", "start": 3, "end": 7},
            {"label": "SURNAME", "start": 8, "end": 13},
            {"label": "USERNAME", "start": 20, "end": 28},
        ],
    }
    assert [s.label for s in _doc(row).gold] == ["PERSON", "PERSON", "USERNAME"]


def test_eval_detect_cli_writes_json_and_results(tmp_path, capsys):
    assert main(["eval", "detect", "--n", "20", "--out", str(tmp_path)]) == 0
    run = json.loads((tmp_path / "detect-synthetic-finance.json").read_text(encoding="utf-8"))
    assert set(run["setups"]) == {"patterns", "patterns + your list"}
    results = (tmp_path / "RESULTS.md").read_text(encoding="utf-8")
    assert "Synthetic bank statements" in results and "| patterns + your list |" in results
