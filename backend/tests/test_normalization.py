"""Pure unit tests (no database needed beyond the shared session fixture)."""

import pytest

from app.services.normalization import (
    email_domain,
    normalize_company_name,
    normalize_domain,
    normalize_phone,
    normalize_website,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Café Beirut S.A.L.", "cafe beirut"),
        ("  ACME   Trading LLC ", "acme trading"),
        ("Smith & Sons Ltd.", "smith and sons"),
        ("Demo Manufacturing Company", "demo manufacturing company"),
        ("Gulf Tech FZ-LLC", "gulf tech"),
        ("SAL", "sal"),  # never strip the whole name
    ],
)
def test_normalize_company_name(raw, expected):
    assert normalize_company_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://WWW.Example.com/about?x=1", "example.com"),
        ("example.com", "example.com"),
        ("http://shop.example.co.uk:8080", "shop.example.co.uk"),
        ("not a url", None),
        ("info@example.com", None),
        ("localhost", None),
        ("http://192.168.1.1", None),
        ("", None),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


def test_normalize_website_adds_scheme():
    assert normalize_website("example.com") == "https://example.com"
    assert normalize_website("http://example.com") == "http://example.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+961 1 234 567", "+9611234567"),
        ("00961-3-123456", "+9613123456"),
        ("01 234 567", None),  # local format: country code unknown
        ("+12", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("01 234 567", "+9611234567"), ("03 123 456", "+9613123456"), ("71 123 456", "+96171123456"),
     ("+961 1 234 567", "+9611234567")],
)
def test_lebanese_local_numbers_with_country(raw, expected):
    assert normalize_phone(raw, "Lebanon") == expected


def test_abc_foods_variants_normalise_identically():
    variants = ["ABC Foods SAL", "ABC Foods S.A.L.", "ABC FOODS", "  abc   foods, s.a.r.l. "]
    assert {normalize_company_name(v) for v in variants} == {"abc foods"}


def test_email_domain_ignores_personal_mailboxes():
    assert email_domain("Rami@ABCFoods.example") == "abcfoods.example"
    assert email_domain("someone@gmail.com") is None
    assert email_domain("not-an-email") is None
