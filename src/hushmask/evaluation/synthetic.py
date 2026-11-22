"""Seeded generator of labelled bank statements (Indian and European formats).

Every personal value is recorded as a gold span, every merchant as a "keep" span, and every transaction
carries its true category, so the same data measures leaks, over-masking and AI accuracy.

Bias warning: these formats were written by the same people who wrote the detectors, so this data flatters
pattern detection. That's why the ai4privacy set is evaluated too.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .. import validators as v
from ..detectors import KnownValue
from ..entities import EntityType as T
from .metrics import Doc, Span

FIRST_IN = ["Rahul", "Priya", "Amit", "Sunita", "Vikram", "Neha", "Arjun", "Kavya", "Rohan", "Ananya", "Sanjay",
            "Pooja", "Imran", "Fatima", "Harpreet", "Lakshmi"]  # fmt: skip
LAST_IN = ["Sharma", "Mehta", "Kumar", "Rao", "Singh", "Gupta", "Iyer", "Nair", "Reddy", "Khan", "Patel", "Das",
           "Joshi", "Banerjee"]  # fmt: skip
FIRST_EU = ["Anna", "Lukas", "Sophie", "Jonas", "Marie", "Pierre", "Camille", "Lucas", "Elena", "Mateo", "Sanne",
            "Daan", "Giulia", "Marco"]  # fmt: skip
LAST_EU = ["Weber", "Müller", "Schmidt", "Dubois", "Martin", "Garcia", "Rossi", "Jansen", "Novak", "Kowalski",
           "Fischer", "Bakker"]  # fmt: skip

MERCHANTS = [
    ("SWIGGY", "Food"), ("ZOMATO", "Food"), ("DOMINOS PIZZA", "Food"), ("AMAZON PAY", "Shopping"),
    ("FLIPKART", "Shopping"), ("MYNTRA", "Shopping"), ("UBER", "Transport"), ("OLA CABS", "Transport"),
    ("IRCTC", "Travel"), ("INDIGO AIRLINES", "Travel"), ("NETFLIX", "Subscriptions"), ("SPOTIFY", "Subscriptions"),
    ("REWE", "Groceries"), ("LIDL", "Groceries"), ("ALBERT HEIJN", "Groceries"), ("BIGBASKET", "Groceries"),
    ("STARBUCKS", "Coffee"), ("SHELL", "Fuel"), ("HP PETROL PUMP", "Fuel"), ("APOLLO PHARMACY", "Health"),
    ("AIRTEL", "Bills"), ("VODAFONE", "Bills"),
]  # fmt: skip
CATEGORIES = sorted({c for _, c in MERCHANTS} | {"Income", "Rent", "Refund", "Transfer"})
CITIES_IN = ["BENGALURU", "MUMBAI", "PUNE", "DELHI", "CHENNAI"]
CITIES_EU = ["BERLIN", "MUNICH", "PARIS", "AMSTERDAM", "MADRID", "MILAN"]
BANKS_IN = ["HDFC BANK", "ICICI BANK", "STATE BANK OF INDIA", "AXIS BANK"]
BANKS_EU = ["DEUTSCHE BANK", "ING", "BNP PARIBAS", "N26"]
STREETS_IN = ["MG Road", "Linking Road", "Park Street", "Anna Salai", "Brigade Road"]
# Written the way each country writes them: name + number + postcode + city, or number + name for France.
ADDRESSES_EU = [
    "Hauptstraße {n}, {zip} Berlin",
    "Lindenallee {n}, {zip} Köln",
    "Keizersgracht {n}, 1015 CJ Amsterdam",
    "{n} rue de Rivoli, 75001 Paris",
    "Calle Mayor {n}, 28013 Madrid",
    "Via Roma {n}, 00184 Roma",
]
UPI_BANKS = ["okhdfcbank", "ybl", "paytm", "oksbi", "okicici"]
MAIL_HOSTS = ["gmail.com", "outlook.com", "corp.in", "web.de", "proton.me"]
PERSON_LINES = [("SALARY", "Income"), ("RENT", "Rent"), ("REFUND", "Refund"), ("", "Transfer")]


@dataclass
class Transaction:
    category: str
    counterparty: str
    is_person: bool


class _Builder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.length = 0
        self.gold: list[Span] = []
        self.keep: list[Span] = []

    def add(self, text: str, label: str | None = None, *, keep: bool = False) -> None:
        if label:
            self.gold.append(Span(label, self.length, self.length + len(text)))
        if keep:
            self.keep.append(Span("MERCHANT", self.length, self.length + len(text)))
        self.parts.append(text)
        self.length += len(text)

    @property
    def text(self) -> str:
        return "".join(self.parts)


def generate(n: int, seed: int = 7) -> list[Doc]:
    rng = random.Random(seed)
    return [_statement(rng) for _ in range(n)]


def _statement(rng: random.Random) -> Doc:
    eu = rng.random() < 0.4
    first, last = (FIRST_EU, LAST_EU) if eu else (FIRST_IN, LAST_IN)
    holder = f"{rng.choice(first)} {rng.choice(last)}"
    cities = CITIES_EU if eu else CITIES_IN
    if eu:
        address = rng.choice(ADDRESSES_EU).format(n=rng.randint(1, 120), zip=rng.randint(10000, 99999))
    else:
        street, city = rng.choice(STREETS_IN), rng.choice(cities).title()
        address = f"{rng.randint(1, 120)} {street}, {city} {rng.randint(400001, 699999)}"
    b = _Builder()

    # header
    if rng.random() < 0.5:
        b.add(f"{rng.choice(BANKS_EU if eu else BANKS_IN)} statement for ")
        b.add(holder if rng.random() < 0.7 else holder.upper(), T.PERSON)
        b.add("\n")
    else:
        b.add("Account holder: ")
        b.add(holder, T.PERSON)
        b.add("\n")
    if eu:
        b.add("IBAN: ")
        b.add(_iban(rng), T.IBAN)
    else:
        b.add(rng.choice(["A/c No. ", "Account Number: ", "Acct # "]))
        b.add(_digits(rng, rng.randint(11, 16)), T.ACCOUNT)
        b.add("   IFSC: ")
        b.add(_ifsc(rng), T.IFSC)
    b.add("\nAddress: ")
    b.add(address, T.ADDRESS)
    b.add("\n")
    if not eu and rng.random() < 0.4:
        b.add("PAN: ")
        b.add(_pan(rng), T.PAN)
        b.add("  Aadhaar: ")
        b.add(_aadhaar(rng), T.AADHAAR)
        b.add("\n")
    b.add("\n")

    # transactions
    transactions: list[Transaction] = []
    card = _card(rng)
    for _i in range(rng.randint(5, 9)):
        b.add(f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/2026  ")
        amount = f"{rng.randint(50, 90000):,}.{rng.randint(0, 99):02d}"
        if rng.random() < 0.35:  # a person
            name = f"{rng.choice(first)} {rng.choice(last)}"
            shown = name.upper()
            word, category = rng.choice(PERSON_LINES)
            style = rng.randint(0, 3)
            if eu:
                b.add("SEPA ÜBERWEISUNG AN " if category != "Income" else "SEPA GUTSCHRIFT VON ")
                b.add(shown, T.PERSON)
                b.add(f" {word}" if word else "")
            elif style == 0:
                b.add("UPI/")
                handle = f"{name.split()[0].lower()}.{name.split()[1].lower()}@{rng.choice(UPI_BANKS)}"
                b.add(handle, T.UPI)
                b.add("/")
                b.add(shown, T.PERSON)
                b.add(f" {word}" if word else "")
            elif style == 1:
                b.add("NEFT FROM " if category in ("Income", "Refund") else "IMPS TO ")
                b.add(shown, T.PERSON)
                b.add(f" {word}" if word else "")
            else:
                b.add("BY TRANSFER-NEFT-" if category in ("Income", "Refund") else "TO TRANSFER-IMPS-")
                b.add(shown, T.PERSON)
                b.add(f"-{word}" if word else "")
            transactions.append(Transaction(category, name, True))
            sign = "Cr" if category in ("Income", "Refund") else "Dr"
        else:
            merchant, category = rng.choice(MERCHANTS)
            style = rng.randint(0, 2)
            if style == 0:
                b.add("POS ")
                b.add(card, T.CARD)
                b.add(" ")
                b.add(merchant, keep=True)
                b.add(" ")
                b.add(rng.choice(cities), T.LOCATION)
            elif style == 1:
                b.add("UPI/")
                b.add(merchant, keep=True)
                b.add(f"/{rng.randint(100000000, 999999999)}")
            else:
                b.add(merchant, keep=True)
            transactions.append(Transaction(category, merchant, False))
            sign = "Dr"
        b.add(f"  {amount} {sign}\n")

    # footer and a free-text note
    b.add("\nQuestions? Write to ")
    email_name = holder.lower().replace(" ", rng.choice([".", "", "_"]))
    b.add(f"{email_name}@{rng.choice(MAIL_HOSTS)}", T.EMAIL)
    b.add(" or call ")
    b.add(_phone(rng, eu), T.PHONE)
    b.add(".\n")
    if rng.random() < 0.5:
        friend = f"{rng.choice(first)} {rng.choice(last)}"
        b.add("Note: reimburse ")
        b.add(friend, T.PERSON)
        b.add(" for the trip to ")
        b.add(rng.choice(cities).title(), T.LOCATION)
        b.add(f". Dear {'Mr' if rng.random() < 0.5 else 'Ms'} ")
        b.add(holder.split()[1], T.PERSON)
        b.add(", thank you.\n")

    known = [KnownValue(holder, T.PERSON), KnownValue(address, T.ADDRESS)]
    return Doc(b.text, b.gold, b.keep, known, {"region": "EU" if eu else "IN", "transactions": transactions})


# -- valid-looking numbers ------------------------------------------------------------------------


def _digits(rng: random.Random, n: int) -> str:
    return str(rng.randint(1, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(n - 1))


def _card(rng: random.Random) -> str:
    body = "4" + "".join(str(rng.randint(0, 9)) for _ in range(14))
    number = next(body + str(d) for d in range(10) if v.luhn(body + str(d)))
    return rng.choice(
        [
            " ".join(number[i : i + 4] for i in range(0, 16, 4)),
            "-".join(number[i : i + 4] for i in range(0, 16, 4)),
            number,
        ]
    )


def _iban(rng: random.Random) -> str:
    country, bban = rng.choice([("DE", _digits(rng, 18)), ("NL", "ABNA" + _digits(rng, 10))])
    numeric = "".join(str(int(c, 36)) for c in bban + country + "00")
    compact = f"{country}{98 - int(numeric) % 97:02d}{bban}"
    assert v.iban(compact)
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4)) if rng.random() < 0.7 else compact


def _aadhaar(rng: random.Random) -> str:
    prefix = str(rng.randint(2, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(10))
    number = next(prefix + str(d) for d in range(10) if v.aadhaar(prefix + str(d)))
    return f"{number[:4]} {number[4:8]} {number[8:]}" if rng.random() < 0.7 else number


def _pan(rng: random.Random) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return (
        "".join(rng.choice(letters) for _ in range(3))
        + "P"
        + rng.choice(letters)
        + _digits(rng, 4)
        + rng.choice(letters)
    )


def _ifsc(rng: random.Random) -> str:
    return rng.choice(["HDFC", "ICIC", "SBIN", "UTIB"]) + "0" + _digits(rng, 6)


def _phone(rng: random.Random, eu: bool) -> str:
    if eu:
        return rng.choice(
            [
                f"+49 151 {_digits(rng, 8)}",
                f"+33 6 {rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
                f"+31 6 {_digits(rng, 8)}",
            ]
        )
    mobile = str(rng.randint(6, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(9))
    return rng.choice([f"+91 {mobile[:5]} {mobile[5:]}", mobile, f"0{mobile}"])
