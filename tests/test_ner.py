import os

import pytest

from hushmask import EntityType, GlinerDetector, KnownValue, Masker, Policy
from hushmask.ner import available as ner_available
from hushmask.ner import chunks, model_view, trim_span


class FakeModel:
    """Finds the given phrases (case-insensitive) in whatever view it is shown, and records what it saw."""

    def __init__(self, phrases: dict[str, str]):
        self.phrases = phrases
        self.seen: list[str] = []

    def predict_entities(self, text, labels, threshold=0.5):
        self.seen.append(text)
        found = []
        for phrase, label in self.phrases.items():
            start = text.casefold().find(phrase.casefold())
            if start >= 0 and label in labels:
                found.append({"start": start, "end": start + len(phrase), "label": label, "score": 0.9})
        return found


def test_model_view_keeps_length_and_fixes_caps_and_separators():
    text = "04/11 BY TRANSFER-NEFT-SUNITA RAO-REFUND 1,200.00\nHi Neha, see you"
    view = model_view(text)
    assert len(view) == len(text)
    assert "Sunita Rao" in view
    assert "Hi Neha, see you" in view  # mixed-case lines are left alone


def test_chunks_cover_text_with_correct_offsets():
    text = "\n".join(f"line {i} " + "x" * 30 for i in range(50))
    pieces = list(chunks(text, 200))
    assert "".join(p for _, p in pieces) == text
    assert all(text[o : o + len(p)] == p for o, p in pieces)
    assert all(len(p) <= 200 for _, p in pieces)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("NEFT-SUNITA RAO", "SUNITA RAO"),
        ("IMPS TO AMIT KUMAR", "AMIT KUMAR"),
        ("Dr. Vikram Singh,", "Dr. Vikram Singh"),
        ("NEFT REFUND", ""),
    ],
)
def test_trim_span(text, expected):
    start, end = trim_span(text, 0, len(text))
    assert text[start:end] == expected


def test_detector_maps_offsets_back_to_original_text():
    model = FakeModel({"sunita rao": "person", "koramangala": "city"})
    text = "01/11 UPI-ZOMATO 312.00\n04/11 BY TRANSFER-NEFT-SUNITA RAO-REFUND 1,200.00\nMCDONALDS KORAMANGALA"
    found = GlinerDetector(model).detect(text)
    assert [(e.type, e.text) for e in found] == [
        (EntityType.PERSON, "SUNITA RAO"),
        (EntityType.LOCATION, "KORAMANGALA"),
    ]
    assert "Sunita Rao" in model.seen[0]  # the model read the cleaned-up view


def test_spans_containing_a_label_word_are_dropped():
    # Real model behaviour: "the person or merchant" came back as a person.
    model = FakeModel({"person or merchant": "person", "anna weber": "person"})
    found = GlinerDetector(model).detect("counterparty is the person or merchant, e.g. Anna Weber")
    assert [e.text for e in found] == ["Anna Weber"]


def test_unknown_labels_are_ignored():
    model = FakeModel({"starbucks": "organization"})
    assert GlinerDetector(model, labels={"person": EntityType.PERSON}).detect("STARBUCKS 380.00") == []


def test_finance_preset_keeps_cities_inside_merchants():
    model = FakeModel({"amit kumar": "person", "koramangala": "city"})
    masker = Masker(policy=Policy.preset("finance"), extra_detectors=[GlinerDetector(model)])
    text = masker.mask("IMPS TO AMIT KUMAR\nMCDONALDS KORAMANGALA 289.00").text
    assert "AMIT" not in text
    assert "MCDONALDS KORAMANGALA" in text


def test_model_noise_does_not_fail_the_guard():
    class Flaky(FakeModel):
        def predict_entities(self, text, labels, threshold=0.5):
            # finds "Neha" only the second time (as if context changed), which must not raise
            found = super().predict_entities(text, labels, threshold) if self.seen else []
            self.seen.append(text)
            return found

    masker = Masker(extra_detectors=[GlinerDetector(Flaky({"neha": "person"}))])
    assert "Neha" in masker.mask("thanks Neha").text


def test_model_names_link_to_known_full_name():
    model = FakeModel({"mr sharma": "person"})
    masker = Masker(known=[KnownValue("Rahul Sharma", EntityType.PERSON)], extra_detectors=[GlinerDetector(model)])
    result = masker.mask("Dear Mr Sharma, Rahul Sharma's card")
    full, variant = result.tokens[1], result.tokens[0]
    assert variant == f"{full}_1"
    assert masker.restore(result.text).text == "Dear Mr Sharma, Rahul Sharma's card"


real_model = pytest.mark.skipif(
    not ner_available() or os.environ.get("HUSHMASK_MODEL_TESTS") != "1",
    reason="set HUSHMASK_MODEL_TESTS=1 and install the 'ner' extra to run real-model tests",
)


@real_model
def test_real_model_on_statement():
    text = (
        "01/11 IMPS TO AMIT KUMAR RENT NOV 18,000.00 DR\n"
        "02/11 UPI-ZOMATO-PAYTM 312.00 DR\n"
        "03/11 SEPA ÜBERWEISUNG AN ANNA WEBER MIETE 750,00\n"
        "04/11 BY TRANSFER-NEFT-SUNITA RAO-REFUND 1,200.00 CR\n"
        "05/11 MCDONALDS KORAMANGALA 289.00 DR\n"
        "Please reimburse Neha Gupta for the trip. Her manager is Dr. Vikram Singh.\n"
    )
    masker = Masker(policy=Policy.preset("finance"), extra_detectors=[GlinerDetector()])
    masked = masker.mask(text).text
    for name in ["AMIT", "KUMAR", "ANNA", "WEBER", "SUNITA", "Neha", "Vikram"]:
        assert name not in masked, name
    for kept in ["ZOMATO", "MCDONALDS", "18,000.00", "NEFT"]:
        assert kept in masked, kept
    assert masker.restore(masked).text == text
