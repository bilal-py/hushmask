import pytest

from hushmask import validators as v


def make_aadhaar(prefix: str) -> str:
    """Append the one check digit that makes an 11-digit prefix a valid Aadhaar."""
    return next(prefix + str(d) for d in range(10) if v.aadhaar(prefix + str(d)))


@pytest.mark.parametrize("number", ["4111 1111 1111 1111", "5555-5555-5555-4444", "378282246310005"])
def test_luhn_accepts_test_cards(number):
    assert v.luhn(number)


@pytest.mark.parametrize("number", ["4111 1111 1111 1112", "1234", "12345678901234567890"])
def test_luhn_rejects(number):
    assert not v.luhn(number)


@pytest.mark.parametrize(
    "value", ["DE89 3704 0044 0532 0130 00", "GB82WEST12345698765432", "FR1420041010050500013M02606"]
)
def test_iban_accepts(value):
    assert v.iban(value)


def test_iban_rejects_bad_checksum():
    assert not v.iban("DE89 3704 0044 0532 0130 01")


def test_aadhaar():
    valid = make_aadhaar("23412341234")
    assert v.aadhaar(valid)
    assert not v.aadhaar(valid[:-1] + str((int(valid[-1]) + 1) % 10))
    assert not v.aadhaar("1" + valid[1:])  # never starts with 0 or 1


def test_ipv4():
    assert v.ipv4("192.168.1.20")
    assert not v.ipv4("256.1.1.1")
    assert not v.ipv4("01.2.3.4")
