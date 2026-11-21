import re

import pytest

from hushmask import EntityType, KnownValue, LeakError, Masker, PatternDetector

STATEMENT = """Statement for Rahul Sharma, Account Number: 50100123456789
12/11/2026 UPI/rahul.sharma@okhdfcbank/SWIGGY 450.00 Dr
13/11/2026 CARD 4111 1111 1111 1111 AMAZON 1,299.00 Dr
Questions? rahul.sharma@example.com or +91 98765 43210"""

KNOWN = [KnownValue("Rahul Sharma", EntityType.PERSON)]


def test_mask_hides_everything_and_keeps_merchants():
    result = Masker(known=KNOWN).mask(STATEMENT)
    for secret in ["Rahul", "Sharma", "50100123456789", "4111", "okhdfcbank", "example.com", "98765"]:
        assert secret.casefold() not in result.text.casefold()
    for kept in ["SWIGGY", "AMAZON", "450.00", "1,299.00", "12/11/2026"]:
        assert kept in result.text


def test_round_trip():
    masker = Masker(known=KNOWN)
    masked = masker.mask(STATEMENT).text
    restored = masker.restore(masked)
    assert restored.text == STATEMENT
    assert restored.unknown == frozenset()


def test_same_value_same_token_across_calls():
    masker = Masker()
    a = masker.mask("card 4111 1111 1111 1111").tokens
    b = masker.mask("again 4111-1111-1111-1111").tokens
    assert a == b


def test_phone_variants_share_a_token():
    masker = Masker()
    tokens = masker.mask("+91 98765 43210 / 09876543210 / 9876543210").tokens
    assert len(set(tokens)) == 1


def test_fixed_secret_gives_stable_tokens_across_sessions():
    a = Masker(secret=b"k" * 32).mask("x@example.com").text
    b = Masker(secret=b"k" * 32).mask("x@example.com").text
    c = Masker(secret=b"z" * 32).mask("x@example.com").text
    assert a == b != c


def test_token_shape():
    text = Masker().mask("x@example.com").text
    assert re.fullmatch(r"EMAIL_[0-9a-f]{6}", text)


def test_restore_tolerates_model_changing_case():
    masker = Masker()
    token = masker.mask("x@example.com").tokens[0]
    assert masker.restore(f"Send to {token.lower()}.").text == "Send to x@example.com."


def test_restore_reports_invented_tokens():
    masker = Masker()
    masker.mask("x@example.com")
    result = masker.restore("PERSON_abcdef paid")
    assert result.text == "PERSON_abcdef paid"
    assert result.unknown == {"PERSON_abcdef"}


def test_restore_ignores_unrelated_underscored_words():
    masker = Masker()
    assert masker.restore("cafe_beef12 and snake_case").unknown == frozenset()


def test_restore_json():
    masker = Masker(known=KNOWN)
    masked = masker.mask("Rahul Sharma paid 450.00 to Swiggy").text
    person = masked.split(" paid")[0]
    model_output = {"transactions": [{"description": f"{person} paid Swiggy", "amount": 450.0, "tags": [person]}]}
    restored, info = masker.restore_json(model_output)
    assert restored == {
        "transactions": [{"description": "Rahul Sharma paid Swiggy", "amount": 450.0, "tags": ["Rahul Sharma"]}]
    }
    assert info.restored == {person}


def test_vault_is_read_only():
    masker = Masker()
    masker.mask("x@example.com")
    with pytest.raises(TypeError):
        masker.vault["EMAIL_000000"] = "y"  # type: ignore[index]


def test_guard_fails_closed_when_a_value_survives():
    # A detector that only catches the first card leaves the second copy (glued to a word) visible.
    import re as _re

    first_only = PatternDetector("first", EntityType.CARD, _re.compile(r"^4111111111111111"), 50)
    masker = Masker(detectors=[first_only])
    with pytest.raises(LeakError) as err:
        masker.mask("4111111111111111 then ref4111111111111111")
    assert "4111" not in str(err.value)
