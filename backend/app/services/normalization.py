"""Normalisation helpers that prepare company records for future identity resolution.

These are intentionally simple and deterministic. Phase 1 will build duplicate
detection on top of `normalized_name`, `domain` and `main_phone_normalized`.
"""

import re
import unicodedata
from urllib.parse import urlsplit

# Trailing legal-form tokens stripped from normalised names (after dots are removed).
_LEGAL_SUFFIXES = {
    "sal", "sarl", "llc", "ltd", "limited", "inc", "incorporated", "corp", "corporation",
    "co", "plc", "gmbh", "fze", "fzco", "fz", "wll", "sa", "sas", "bv", "pvt", "pte",
}
_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_company_name(name: str) -> str:
    """'Café Beirut S.A.L.' -> 'cafe beirut'."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ").replace(".", "")
    text = re.sub(r"[^\w\s]|_", " ", text)
    tokens = text.split()
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_domain(value: str | None) -> str | None:
    """'https://WWW.Example.com/about' -> 'example.com'. Returns None when invalid."""
    if not value:
        return None
    candidate = value.strip().lower()
    if not candidate or "@" in candidate or any(ch.isspace() for ch in candidate):
        return None
    if "://" not in candidate:
        candidate = "http://" + candidate
    try:
        parsed = urlsplit(candidate)
        host = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not host:
        return None
    host = host.rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    labels = host.split(".")
    if len(labels) < 2 or not all(_LABEL_RE.match(label) for label in labels):
        return None
    if labels[-1].isdigit():  # bare IP addresses are not company domains
        return None
    return host


def normalize_website(value: str | None) -> str | None:
    """Store websites with an explicit scheme so they render as working links."""
    if not value:
        return None
    value = value.strip()
    return value if "://" in value else f"https://{value}"


# Country dialling codes used to normalise local-format numbers. Lebanon is the
# initial market; extend as new markets are added.
_DIAL_CODES = {"lebanon": "961", "lb": "961"}


def normalize_phone(value: str | None, country: str | None = None) -> str | None:
    """Best-effort E.164.

    International numbers (+961..., 00961...) are always converted. Local numbers
    (01 234 567, 03 123 456, 71 123 456) are converted only when the country is known.
    """
    if not value:
        return None
    raw = value.strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        full = digits
    elif raw.startswith("00"):
        full = digits[2:]
    else:
        code = _DIAL_CODES.get((country or "").strip().lower())
        if not code or not digits:
            return None
        full = code + digits.lstrip("0")
    if 7 <= len(full) <= 15 and not full.startswith("0"):
        return f"+{full}"
    return None


# Personal mailbox providers: their domain says nothing about the company.
FREE_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "hotmail.com", "hotmail.fr", "outlook.com", "live.com",
        "msn.com", "yahoo.com", "yahoo.fr", "ymail.com", "icloud.com", "me.com", "aol.com",
        "proton.me", "protonmail.com", "gmx.com", "mail.com", "zoho.com", "yandex.com",
        "idm.net.lb", "cyberia.net.lb", "terra.net.lb", "inco.com.lb",
    }
)


def email_domain(email: str | None) -> str | None:
    """Company domain of an email address, or None for personal/free mailboxes."""
    if not email or "@" not in email:
        return None
    domain = normalize_domain(email.strip().rsplit("@", 1)[1])
    if domain is None or domain in FREE_EMAIL_DOMAINS:
        return None
    return domain


def name_key(value: str | None) -> str | None:
    """Case/whitespace-insensitive key for people and team names."""
    if not value:
        return None
    key = " ".join(value.split()).lower()
    return key or None
