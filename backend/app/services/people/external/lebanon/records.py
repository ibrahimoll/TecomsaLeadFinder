"""Directory records and how they are tied to LeadFinder companies.

A Record is one statement of a public directory, kept exactly as published:
    org      the organisation's names as the source writes them (English / French / Arabic, acronym)
    person   + title   "Mr. Hamad Al Oqab" / "Chairman & General Manager" (None: an organisation-only entry)
    excerpt  the line(s) it was read from, page (PDFs), its own date when it carries one
Records are parsed ONCE per document version and kept with the cached document (external_documents.content);
every company is then matched locally, without any further request.

Matching a record to a company (never on a vague similarity):
    same company domain (website / e-mail published in the record)            92
    same name after legal forms (SAL, S.A.R.L., ش.م.ل, Ets., Société...)        88
    same distinctive core ('Arabia Insurance Co.' ~ 'Arabia Insurance') 80
A group / holding is another entity: 'X Group' never matches 'X' (and the reverse).
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Evidence
from app.services.discovery.geography import _fold
from app.services.normalization import company_domain
from app.services.people.candidate import PersonCandidate
from app.services.people.names import clean_name, is_person_name, is_placeholder, split_name
from app.services.people.titles import classify

RECENT = timedelta(days=548)  # ~18 months: an official statement this recent supports a current role
_LEGAL = {"sal", "sarl", "sa", "sas", "ltd", "llc", "inc", "co", "company", "compagnie", "cie", "corp",
          "corporation", "societe", "ste", "ets", "etablissements", "establishment", "est", "the", "plc", "limited",
          "شمل", "شمم", "شركه", "مؤسسه", "شركة", "مؤسسة", "موسسه", "موسسة", "and", "et", "of", "de", "du", "des", "d", "la", "le",
          "les", "au", "aux", "en", "al", "el", "و", "في", "تضامن", "توصيه", "pour", "for", "par",
          "fz", "fze", "fzco", "fzc", "dmcc", "wll", "spc", "pjsc", "psc", "qsc", "bsc", "jsc", "gmbh", "bv", "srl"}
# Sector words: a name without them must still be distinctive ('Arabia Insurance Co.' ~ 'Arabia Insurance').
_SECTOR = {"bank", "banque", "banca", "insurance", "insurances", "assurance", "assurances", "reinsurance",
           "reassurance", "reassurances", "takaful", "lebanon", "liban", "lebanese", "libanais", "libanaise",
           "international", "sal", "تامين", "للتامين", "بنك", "مصرف", "لبنان"}
# French / English forms of the same business word: 'Banque X' ~ 'X Bank'... compared as one (matching aid only)
_EQUIVALENT = {"banque": "bank", "banca": "bank", "assurances": "insurance", "assurance": "insurance",
               "insurances": "insurance", "reassurance": "reinsurance", "reassurances": "reinsurance",
               "libanaise": "lebanese", "libanais": "lebanese", "liban": "lebanon", "generale": "general",
               "general": "general", "nationale": "national", "internationale": "international", "groupe": "group",
               "laboratoires": "laboratories", "laboratoire": "laboratory", "pharmaceutiques": "pharmaceuticals",
               "pharmaceutique": "pharmaceutical", "industrielle": "industrial", "industriel": "industrial",
               "commerciale": "commercial", "techniques": "technical", "technique": "technical",
               "ingenierie": "engineering", "imprimerie": "printing", "transports": "transport",
               "ecole": "school", "ecoles": "schools", "hopital": "hospital", "clinique": "clinic",
               "pharmacie": "pharmacy", "universite": "university", "centre": "center", "societe": "company",
               "compagnie": "company", "hotellerie": "hospitality", "medicale": "medical", "medical": "medical"}
GROUP_WORDS = {"group", "groupe", "holding", "holdings", "global", "worldwide", "مجموعه"}
# Places: a place alone never identifies an organisation ('Chamber of Commerce of Beirut' read as 'Beirut' is not
# 'Bank of Beirut'); inside a longer name they still count ('Kassatly Chtaura')
PLACES = {"beirut", "beyrouth", "tripoli", "saida", "sidon", "tyre", "sour", "zahle", "zahleh", "jounieh", "byblos",
          "jbeil", "baabda", "metn", "bekaa", "chtaura", "aley", "batroun", "nabatieh", "koura", "kesrouan",
          "keserwan", "achrafieh", "hamra", "dbayeh", "beirut's", "بيروت", "طرابلس", "صيدا", "صور", "زحله", "زحلة",
          "جونيه", "جبيل", "بعبدا", "المتن", "البقاع", "شتوره", "شتورة"}


@dataclass
class Record:
    org: list[str]
    person: str | None = None
    title: str | None = None
    excerpt: str = ""
    page: int | None = None
    domains: list[str] = field(default_factory=list)
    identifiers: dict[str, str] = field(default_factory=dict)
    email: str | None = None  # only when published for this person
    phone: str | None = None
    status: str | None = None  # "former" / "unknown" when the source says so (a founder is not a position)
    published: str | None = None  # the record's own date (ISO), when it carries one
    bio: str | None = None  # association profile text: company roles read at match time
    association_role: str | None = None  # the person's office at the association itself (never a company title)
    # company facts the source states (organisation records): phone, email, address, city, location_type,
    # employees (exact), branches, founded, beds, legal_name, legal_form, signals [...], relationships [...]
    facts: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], {}, "")}

    @classmethod
    def from_json(cls, data: dict) -> "Record":
        return cls(**{"org": [], **data})


def org_key(name: str) -> str:
    """'BANQUE LIBANO-FRANÇAISE S.A.L.' -> 'banque libano francaise'; 'ش.م.ل' and spaced letters joined."""
    text = _fold(name.replace("&", " and ").replace("ـ", ""))
    tokens, letters = [], []
    for t in text.split():
        if len(t) == 1:  # "s a l" / "ش م ل" (dots already removed)
            letters.append(t)
            continue
        if letters:
            tokens.append("".join(letters))
            letters = []
        tokens.append(t)
    if letters:
        tokens.append("".join(letters))
    # word order ignored: 'Banque Libanaise pour le Commerce' ~ 'Lebanese Bank for Commerce'
    return " ".join(sorted(_EQUIVALENT.get(t, t) for t in tokens if t not in _LEGAL))


def core_key(key: str) -> str | None:
    """The distinctive part of an organisation key, or None when what remains is too generic to identify it."""
    tokens = [t for t in key.split() if t not in _SECTOR]
    if not tokens or (len(tokens) == 1 and len(tokens[0]) < 4) or all(t in PLACES for t in tokens):
        return None
    return " ".join(tokens)


def name_variants(name: str) -> list[str]:
    """'Laiterie Massabki - البان وأجبان مسابكي' -> both parts; 'SGBL (Société Générale...)' -> both; 'A | B'."""
    parts = [name] + re.split(r"\s+[-–|/]\s+|\s*\|\s*", name)
    for inside in re.findall(r"\(([^)]{2,80})\)", name):
        parts += ([] if inside.strip().isdigit() else [inside]) + [re.sub(r"\([^)]*\)", " ", name)]
    latin = " ".join(w for w in name.split() if not re.search(r"[؀-ۿ]", w))
    arabic = " ".join(w for w in name.split() if re.search(r"[؀-ۿ]", w))
    return [p for p in dict.fromkeys(" ".join(x.split()) for x in (*parts, latin, arabic)) if len(p) >= 2]


def keys_of(names: list[str]) -> tuple[set[str], set[str], set[str]]:
    """(full keys, distinctive cores, acronyms): an acronym is a short name written in capitals ('SNA SAL',
    '(UCA)', 'UCA Insurance'); it only ever matches another acronym."""
    full, core, acronyms = set(), set(), set()
    for name in names:
        for variant in name_variants(name):
            key = org_key(variant)
            if not key:
                continue
            if (len(key.split()) > 1 or len(key) >= 4) and any(t not in _SECTOR for t in key.split()) and \
                    not all(t in PLACES for t in key.split()):
                full.add(key)  # never a bare sector word ("Bank", "Insurance") nor a bare place ("Beirut")
            if c := core_key(key):
                core.add(c)
            shortest = [t for t in key.split() if t not in _SECTOR]
            upper = {w.strip("().,").lower() for w in variant.split() if w.strip("().,").isupper()}
            if len(shortest) == 1 and 2 <= len(shortest[0]) <= 5 and shortest[0] in upper:
                acronyms.add(shortest[0])
    return full, core, acronyms


def company_names(db: Session, company: Company) -> list[str]:
    names = [company.name, company.legal_name]
    names += db.scalars(select(Evidence.extracted_value).where(Evidence.company_id == company.id,
                                                               Evidence.field_name == "trading_name").distinct())
    return [n for n in names if n]


def _groupish(key: str) -> bool:
    return bool(set(key.split()) & GROUP_WORDS)


def match(company_full: set[str], company_core: set[str], company_dom: str | None, record: Record,
          company_acronyms: set[str] = frozenset()) -> int | None:
    """How explicitly the record names this company (None: it does not)."""
    full, core, acronyms = keys_of(record.org)
    # the record's own website (first) only: an e-mail or second address may be a parent group's
    domain = company_dom and record.domains[:1] and company_domain(record.domains[0]) == company_dom
    named = 88 if full & company_full else 80 if core & company_core or acronyms & company_acronyms else None
    if named and any(_groupish(k) for k in full) and not any(_groupish(k) for k in company_full):
        named = None  # 'X Group' is not 'X'
    if domain:
        return 95 if named else 92
    return named


def best_title(raw: str):
    """'Deputy General Manager - Chief Commercial Officer': both roles are held; the recognised, highest-ranked part
    gives the meaning (the raw title is kept whole)."""
    parts = [classify(p) for p in re.split(r"\s+[-–/]\s+", raw) if p.strip()]
    known = [t for t in parts if t and t.explicit]
    whole = classify(raw)
    if known and not (whole and whole.explicit):
        best = min(known, key=lambda t: t.rank)
        return type(best)(raw, best.normalized, best.department, best.seniority, best.rank, True)
    return whole


def published_date(value: str | None) -> datetime | None:
    m = re.search(r"(19\d{2}|20\d{2})-(\d{2})-(\d{2})", value or "")
    return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc) if m else None


def status_for(record: Record, stated: datetime | None, now: datetime | None = None) -> str:
    """Official statements of the last ~18 months support a current role; older or undated: not confirmed."""
    if record.status in ("former", "unknown"):
        return record.status
    now = now or datetime.now(timezone.utc)
    return "current" if stated and now - stated <= RECENT else "unknown"


def candidate(record: Record, *, company_id: int, source_id: int, url: str | None, source_type: str, quality: int,
              match_confidence: int, stated: datetime | None, category: str, document: str | None,
              title: str | None = None, excerpt: str | None = None) -> PersonCandidate | None:
    """The person-role claim of a record, through the same name / title rules as every source (None: not a person,
    a placeholder, or no title)."""
    name = clean_name(record.person or "")
    raw_title = " ".join((title or record.title or "").split()).strip(" ,;:-–—")
    excerpt = excerpt or record.excerpt
    if not raw_title or not is_person_name(name) or is_placeholder(excerpt):
        return None
    meaning = best_title(raw_title)
    first, middle, last = split_name(name)
    status = status_for(record, stated)
    observed = stated or datetime.now(timezone.utc)
    return PersonCandidate(
        source_id=source_id, source_url=url, source_type=source_type, company_id=company_id, full_name=name,
        raw_title=raw_title[:300], evidence_excerpt=(f"Page {record.page}: " if record.page else "") + excerpt[:560],
        observed_at=observed, first_name=first, middle_name=middle, last_name=last,
        normalized_title=meaning.normalized if meaning else None,
        department=meaning.department if meaning else "other", seniority=meaning.seniority if meaning else "unknown",
        title_rank=meaning.rank if meaning else None, title_explicit=bool(meaning and meaning.explicit),
        status=status, email=record.email, phone=_phone(record.phone), source_confidence=quality,
        company_match_confidence=match_confidence,
        raw_metadata={"page": record.page, "category": category, "document": document,
                      "stated": stated.date().isoformat() if stated else None,
                      # how the source labels the number (classify_phone reads it: WhatsApp / mobile / extension)
                      "context": "WhatsApp" if record.phone and record.phone == record.facts.get("whatsapp")
                      else excerpt[:300]})


def _phone(raw: str | None) -> str | None:
    from app.services.normalization import normalize_phone

    return normalize_phone(raw, "Lebanon") if raw else None

