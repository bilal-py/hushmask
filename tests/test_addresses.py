import pytest

from hushmask import EntityType, Masker
from hushmask.addresses import AddressDetector


def addresses(text: str) -> list[str]:
    return [e.text for e in AddressDetector().detect(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # German / Austrian / Swiss / Dutch
        ("She lives at Bergstraße 12, 10115 Berlin.", "Bergstraße 12, 10115 Berlin"),
        ("Lieferadresse Lindenallee 7, 50667 Köln", "Lindenallee 7, 50667 Köln"),
        ("Adresse: Hauptstr. 5a", "Hauptstr. 5a"),
        ("wohnt in der Lange Straße 14-16", "Lange Straße 14-16"),
        ("Marktplatz 3, 8001 Zürich", "Marktplatz 3, 8001 Zürich"),
        ("Keizersgracht 123, 1015 CJ Amsterdam", "Keizersgracht 123, 1015 CJ Amsterdam"),
        ("Am Ring 4, 50667 Köln", "Am Ring 4, 50667 Köln"),
        ("Rosenweg 8, 80331 München", "Rosenweg 8, 80331 München"),
        # US / UK / Australia
        (
            "Ship to 1600 Pennsylvania Ave NW, Washington, DC 20500 today",
            "1600 Pennsylvania Ave NW, Washington, DC 20500",
        ),
        ("Office: 350 Fifth Avenue, Suite 3300", "350 Fifth Avenue, Suite 3300"),
        ("42 Wallaby Way, Sydney NSW 2000", "42 Wallaby Way, Sydney NSW 2000"),
        ("Unit 3/42 Smith St, Fitzroy VIC 3065", "Unit 3/42 Smith St, Fitzroy VIC 3065"),
        ("10 Downing Street, London SW1A 2AA", "10 Downing Street, London SW1A 2AA"),
        ("DELIVER TO 12 MAIN STREET", "12 MAIN STREET"),
        ("117 Park Street, Pune 411001", "117 Park Street, Pune 411001"),
        # French / Italian / Spanish
        ("12 rue de Rivoli, 75001 Paris", "12 rue de Rivoli, 75001 Paris"),
        ("Via Roma 10, 00184 Roma", "Via Roma 10, 00184 Roma"),
        ("Calle Mayor 5, 28013 Madrid", "Calle Mayor 5, 28013 Madrid"),
    ],
)
def test_finds_addresses(text, expected):
    assert addresses(text) == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "Spring 2026 collection",
        "Monitoring 2 servers",
        "paid via PayPal 10.99",
        "PAYMENT VIA PAYPAL 10.99",
        "REWE BERLIN 45.20 Dr",
        "15/11/2026  STARBUCKS  4.80 Dr",
        "Chapter 3 of the report",
        "Order 42 shipped",
        "Room 5 Street Food",  # number first but not "<number> <Name> Street"... still no house-number shape
        "Platz 2 in the ranking",
        "Rated 4.5 St",
    ],
)
def test_leaves_non_addresses_alone(text):
    assert addresses(text) == []


def test_address_masked_end_to_end():
    result = Masker().mask("Please ship it to Bergstraße 12, 10115 Berlin, thanks.")
    assert result.text.startswith("Please ship it to ADDRESS_")
    assert result.entities[0].type is EntityType.ADDRESS
