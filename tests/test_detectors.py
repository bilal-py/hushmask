import pytest

from hushmask import EntityType, KnownValue, Masker, Policy
from tests.test_validators import make_aadhaar


def types_in(text: str, **kwargs) -> list[tuple[EntityType, str]]:
    return [(e.type, e.text) for e in Masker(**kwargs).detect(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail rahul.sharma@example.com today", (EntityType.EMAIL, "rahul.sharma@example.com")),
        ("paid via rahul.sharma@okhdfcbank.", (EntityType.UPI, "rahul.sharma@okhdfcbank")),
        ("card 4111 1111 1111 1111 used", (EntityType.CARD, "4111 1111 1111 1111")),
        ("IBAN DE89 3704 0044 0532 0130 00 BIC COBADEFFXXX", (EntityType.IBAN, "DE89 3704 0044 0532 0130 00")),
        ("PAN ABCPE1234F on file", (EntityType.PAN, "ABCPE1234F")),
        ("IFSC HDFC0001234", (EntityType.IFSC, "HDFC0001234")),
        ("Account Number: 50100123456789", (EntityType.ACCOUNT, "50100123456789")),
        ("A/c No. XXXXXXXX1234 debited", (EntityType.ACCOUNT, "XXXXXXXX1234")),
        ("call +91 98765 43210 now", (EntityType.PHONE, "+91 98765 43210")),
        ("call 9876543210", (EntityType.PHONE, "9876543210")),
        ("office +44 20 7946 0958", (EntityType.PHONE, "+44 20 7946 0958")),
        ("office 020 7946 0958", (EntityType.PHONE, "020 7946 0958")),
        ("from 192.168.1.20", (EntityType.IP, "192.168.1.20")),
    ],
)
def test_detects(text, expected):
    assert types_in(text) == [expected]


@pytest.mark.parametrize("email", ["anna.müller@web.de", "grégori.laudicina@tutanota.com"])
def test_emails_with_accented_letters(email):
    assert types_in(f"write to {email}.") == [(EntityType.EMAIL, email)]


@pytest.mark.parametrize("phone", ["(776) 5008567", "0296 69224164", "0044 92003-6685", "0167 29.907.3017"])
def test_loose_national_phone_formats(phone):
    assert types_in(f"call {phone} today") == [(EntityType.PHONE, phone)]
    assert types_in(f"My number is {phone}.") == [(EntityType.PHONE, phone)]  # sentence-ending full stop


@pytest.mark.parametrize(
    "text",
    ["01.02.2026 1030 ATM", "on 2026-11-22 0930", "ref 0001234", "12/11/2026  POS 380.00 Dr", "Balance 085.50"],
)
def test_loose_phone_ignores_dates_and_short_numbers(text):
    assert [t for t, _ in types_in(text)] == []


def test_phone_leaves_closing_bracket_outside():
    # Found by the dashboard: "(neha@corp.in, +91 98765 43210)" lost its ")" in the masked text.
    assert types_in("(mail, +91 98765 43210)") == [(EntityType.PHONE, "+91 98765 43210")]
    assert types_in("call +44 (20) 7946 0958") == [(EntityType.PHONE, "+44 (20) 7946 0958")]


def test_detects_aadhaar():
    number = make_aadhaar("23412341234")
    spaced = f"{number[:4]} {number[4:8]} {number[8:]}"
    assert types_in(f"Aadhaar {spaced}") == [(EntityType.AADHAAR, spaced)]


@pytest.mark.parametrize(
    "text",
    [
        "12/03/2026 SWIGGY BANGALORE 1,500.00 Dr",
        "TESCO STORES 4521 £23.40",
        "Balance 1,23,456.78 on 2026-11-22",
        "Order #84721 ref 4111 1111 1111 1112",  # fails Luhn
        "Contact support@ for help",
    ],
)
def test_ignores_ordinary_statement_text(text):
    assert types_in(text) == []


def test_known_values_are_case_and_space_insensitive():
    found = types_in("Paid to RAHUL   sharma for rent", known=[KnownValue("Rahul Sharma", EntityType.PERSON)])
    assert found == [(EntityType.PERSON, "RAHUL   sharma")]


def test_known_person_parts_match_alone():
    found = types_in("Dear Mr Sharma,", known=[KnownValue("Rahul Sharma", EntityType.PERSON)])
    assert found == [(EntityType.PERSON, "Sharma")]


def test_known_name_inside_email_masks_whole_email():
    found = types_in("rahul.sharma@example.com", known=[KnownValue("Rahul Sharma", EntityType.PERSON)])
    assert found == [(EntityType.EMAIL, "rahul.sharma@example.com")]


def test_labelled_account_beats_lucky_card_checksum():
    # 50100123456789 happens to pass Luhn; the "Account Number:" label is stronger evidence.
    assert types_in("Account Number: 50100123456789") == [(EntityType.ACCOUNT, "50100123456789")]


def test_known_values_need_whole_words():
    assert types_in("Sharmaji Stores", known=[KnownValue("Sharma", EntityType.PERSON)]) == []


def test_known_value_parse():
    assert KnownValue.parse("PERSON=Rahul Sharma") == KnownValue("Rahul Sharma", EntityType.PERSON)
    assert KnownValue.parse("address = 12 MG Road") == KnownValue("12 MG Road", EntityType.ADDRESS)
    assert KnownValue.parse("Flat 4B=North") == KnownValue("Flat 4B=North", EntityType.CUSTOM)


def test_policy_skips_disabled_types():
    assert types_in("IFSC HDFC0001234", policy=Policy.preset("finance")) == []


def test_known_values_ignore_policy():
    found = types_in(
        "branch HDFC0001234",
        policy=Policy(frozenset()),
        known=[KnownValue("HDFC0001234", EntityType.IFSC)],
    )
    assert found == [(EntityType.IFSC, "HDFC0001234")]


def test_merchants_are_left_alone():
    text = "STARBUCKS RESERVE 450.00\nAMAZON PAY INDIA 1,299.00"
    assert types_in(text, known=[KnownValue("Rahul Sharma", EntityType.PERSON)]) == []
