"""Contributions (Steps 6.1-6.3): authorized business contacts entering LeadFinder's proprietary contact graph -
TECOMSA CRM exports, salesperson-confirmed contacts, business cards, professional e-mail signatures, meeting contacts
and contacts a user adds by hand. One pipeline: explicit (a user contributes, never harvested), attributed (the
contributor, the channel, the source record), scoped (visibility), reversible (suppress), dry run first.

    python -m app.services.contributions FILE CHANNEL [--owner EMAIL] [--visibility organization|managers|private]
                                                  [--apply]
    FILE: .csv / .xlsx (rows), .vcf (business cards), .txt (e-mail signatures, blank-line separated)
    python -m app.services.contributions EXPORT.xlsx LICENSED_DIRECTORY --directory 5INDEX --owner EMAIL [--apply]
                                                  a licensed directory export (5INDEX, Yelleb, Infobel, Kompass, IFP)

    channel                     source type          contact provenance   e-mail status
    ODOO_CRM / CSV_IMPORT       internal_seed        internal_crm         published (confirmed when the row says so)
    SALES_CONFIRMED             internal_seed        human_confirmed      confirmed
    BUSINESS_CARD               business_card        contributed          published
    EMAIL_SIGNATURE             email_signature      contributed          published
    MEETING_CONTACT             meeting_contact      contributed          published (attendance: person <-> e-mail,
                                                                          never a title)
    CONTRIBUTED_BUSINESS_CONTACT contributed_contact contributed          published
    LICENSED_DIRECTORY          licensed_directory   licensed             published (a licensed directory export:
                                                                          5INDEX, Yelleb...; import_directory below)

Resolution (company EXACT / STRONG / POSSIBLE, person EXACT / STRONG / POSSIBLE / NEW, conflicts with colleague-
confirmed titles flagged) and the trail of every contact (contact_evidence) are shared by all channels.
Corroboration: the same work e-mail / phone from another source raises its confidence and is counted; a prediction
attested by a real card / signature / CRM record becomes published (the prediction stays in its trail). A row
without a job title attaches its contacts to a person LeadFinder already knows at the company (same e-mail, else
the same name) and never creates a person. Nothing private: role mailboxes go to nobody, home numbers are not read,
notes are never imported.

Licensed directories (5INDEX, Yelleb, Infobel, Kompass, IFP... exports, CSV / XLSX; their sites are never fetched):
columns detected from common English / French headers (DIRECTORY_COLUMNS); every record names its directory (one
directory's data can be compared / removed alone); a company LeadFinder lacks is CREATED through discovery's own
pipeline (validation, duplicate resolution, persistence: never a duplicate, a deleted company never re-created); a row
naming nobody gives the company its contact points; every source carries the import's id, so one import can be
removed (remove_import) without touching what another source states.
"""

import hashlib
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.models import (AuditLog, Company, CompanyAlias, CompanyDomain, CompanyPerson, ContactEvidence, Email,
                        Evidence, Person, Phone, Source, User)
from app.services import audit_service
from app.services import contact_intelligence as contacts
from app.services.discovery.geography import find_country
from app.services.normalization import normalize_domain, normalize_phone
from app.services.people import persistence
from app.services.people.external import generic
from app.services.people.external.lebanon.records import Record, candidate, org_key, published_date
from app.services.people.names import name_key
from app.services.people.resolution import Match, resolve
from app.services.people.titles import classify, fold

logger = logging.getLogger("leadfinder.contributions")
CHANNELS = {  # channel: (source type, contact provenance, every e-mail confirmed)
    "ODOO_CRM": ("internal_seed", "internal_crm", False),
    "CSV_IMPORT": ("internal_seed", "internal_crm", False),
    "SALES_CONFIRMED": ("internal_seed", "human_confirmed", True),
    "BUSINESS_CARD": ("business_card", "contributed", False),
    "EMAIL_SIGNATURE": ("email_signature", "contributed", False),
    "MEETING_CONTACT": ("meeting_contact", "contributed", False),
    "CONTRIBUTED_BUSINESS_CONTACT": ("contributed_contact", "contributed", False),
    "LICENSED_DIRECTORY": ("licensed_directory", "licensed", False),
    "LUSHA": ("licensed_provider", "lusha", False),  # a paid reveal (services/lusha.py only, never a user's channel)
}
LICENSED = "LICENSED_DIRECTORY"
DIRECTORIES = ("5INDEX", "Yelleb", "Infobel", "Kompass", "IFP")  # suggested; any other name is accepted
DIRECTORY_QUALITY = 85  # lebanon/sources.json licensed_directory
SYSTEMS = tuple(c for c in CHANNELS if c != "LUSHA")
VISIBILITIES = ("organization", "managers", "private")
SEED_COLUMNS = {
    **generic.DEFAULT_COLUMNS,
    "company": r"^(?:company|company name|related company|parent company|account|organi[sz]ation|customer|"
               r"soci[eé]t[eé]|entreprise|الشركة|اسم الشركة)\b",
    "person": r"^(?:contact name|contact|name|display name|full name|person|attendee|participant|nom|الاسم)\b",
    "first_name": r"^(?:first name|given name|pr[eé]nom)\b",
    "last_name": r"^(?:last name|surname|family name|nom de famille)\b",
    "website": r"(?:company domain|domain|website|web site|site web|الموقع)",
    "company_phone": r"^(?:company phone|main phone|switchboard|standard)\b",
    "phone": r"^(?:phone|business phone|work phone|office|tel|telephone|t[eé]l[eé]phone|direct|الهاتف)\b",
    "extension": r"^(?:ext|extension|poste)\b",
    "record_id": r"^(?:id|record id|external id|contact id|partner id|reference|ref)\b",
    "owner": r"^(?:salesperson|sales person|sales owner|owner|organizer|organiser|user|responsible|commercial)\b",
    "last_seen": r"^(?:last interaction|last activity|last contact|last updated|meeting date|write date|date)\b",
    "contact_status": r"^(?:contact status|email status|status)\b",
    "employment": r"^(?:current|former|active|employment|still at company)\b",
}
# A licensed directory export: whole-header matches, claimed in this order (a 'Contact Mobile' column is
# the mobile, never the contact's name). 'Owner' / 'General Manager' / 'Gérant' columns hold that person's name.
DIRECTORY_COLUMNS = {
    "fax": r"\bfax\b|t[eé]l[eé]copie",  # ignored
    "email": r"e-?mail|courriel|البريد",
    "whatsapp": r"whats\s?app|^wa(?: number| no\.?)?$|واتساب",  # kept apart from the mobile
    "mobile": r"mobile|\bcell|\bgsm\b|portable|الخلوي|الجوال",
    "website": r"website|web ?site|^web$|^url$|site (?:web|internet)|^internet$|الموقع",
    "phone": r"^(?:phone|phone number|tel|telephone|t[eé]l[eé]phone|t[eé]l|landline|office phone|business phone|"
             r"company phone|main phone|switchboard|standard|الهاتف)\.?\s*\d*$",
    "title": r"^(?:(?:contact |job )?title|(?:contact |job )?position|fonction|poste|designation|role|function|"
             r"qualit[eé]|المنصب|الوظيفة)$",
    "company": r"^(?:company|company name|business|business name|firm|establishment|organi[sz]ation|soci[eé]t[eé]|"
               r"nom de (?:la soci[eé]t[eé]|l'entreprise)|raison sociale|entreprise|[eé]tablissement|trade name|"
               r"nom commercial|الشركة|اسم الشركة|المؤسسة)$",
    "person": r"^(?:contact|contacts?|contact (?:person|name)|key (?:person|contact)|name|full name|nom|"
              r"nom (?:et|&) pr[eé]nom|person(?:ne)?(?: de)? contact|manager|general manager|gm|managing director|"
              r"owner|proprietor|propri[eé]taire|g[eé]rant|directeur(?: g[eé]n[eé]ral)?|pdg|ceo|president|"
              r"responsable|executives?|key executives|management|dirigeants?|الاسم|المدير|المالك)$",
    "first_name": r"^(?:first name|given name|pr[eé]nom)$",
    "last_name": r"^(?:last name|surname|family name|nom de famille)$",
    "sector": r"^(?:sector|activity|activities|industry|category|business activity|secteur|activit[eé]s?|"
              r"cat[eé]gorie|القطاع|النشاط)$",
    "city": r"^(?:city|town|ville|localit[eé]|region|r[eé]gion|caza|district|area|المدينة|المنطقة)$",
    "address": r"^(?:address|adresse|street|rue|location|العنوان)$",
    "country": r"^(?:country|pays|البلد)$",
    "registration_number": r"^(?:registration(?: number| no\.?)?|commercial regist(?:er|ry)(?: no\.?| number)?|"
                           r"cr(?: no\.?)?|rc|registre (?:du )?commerce|السجل التجاري)$",
    "record_id": r"^(?:id|id ?#|id no\.?|ref|reference|r[eé]f[eé]rence)$",
}
_HONORIFIC = re.compile(r"^(?:(?:mr|mrs|ms|miss|mme|mlle|m|dr|eng|ing|me|sheikh|cheikh|prof|h\.\s?e|hon|sir)\.?\s+)+",
                        re.IGNORECASE)
_NOT_A_PERSON = {"company", "store", "shop", "office", "factory", "pharmacy", "showroom", "branch", "main", "plant",
                 "warehouse", "restaurant", "hotel", "clinic", "lab", "sales", "accounting", "reception", "fax", "home"}
CONFIRMED = re.compile(r"^(confirmed|verified|valid|replied|active customer)$", re.IGNORECASE)
INVALID = re.compile(r"^(invalid|bounced|wrong|do not use)$", re.IGNORECASE)
FORMER = re.compile(r"^(former|left|no|false|inactive|ex[- ]?employee|0)$", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"^(?:n/?a|n\.a\.?|none|null|nil|-+|\.+|0+|tbd|not available|non disponible)$",
                          re.IGNORECASE)
WEAK_STATUSES = ("unknown", "predicted", "high_confidence_predicted", "catch_all")


# ---- input formats -------------------------------------------------------------------------------------------------


_SIG_PHONE = re.compile(r"(?P<label>mob(?:ile)?|cell|gsm|whats\s?app|tel|phone|office|direct|t|m|w)?\s*[.:]?\s*"
                        r"(?P<number>\+?\(?\d[\d\s().-]{6,}\d)(?:\s*(?:ext\.?|x|poste)\s*(?P<ext>\d{1,6}))?",
                        re.IGNORECASE)


def parse_signature(text: str) -> dict | None:
    """A professional e-mail signature -> {person, title, company, email, mobile, phone, whatsapp, extension, website}.
    Only the signature block is read (the caller contributes it, never a mailbox): the first line is the name, a line
    the title taxonomy recognises is the title, the e-mail's domain / a website line names the company's site."""
    lines = [" ".join(line.split()).strip(" |-–") for line in text.strip().splitlines()]
    lines = [line for line in lines if line and not re.match(r"^(regards|best|thanks|kind regards|sincerely)", line,
                                                            re.IGNORECASE)]
    if not lines:
        return None
    entry: dict = {"person": lines[0]}
    for line in lines[1:]:
        if m := generic._EMAIL.search(line):
            entry.setdefault("email", m[0])
            continue
        if re.search(r"(https?://|www\.)\S+", line, re.IGNORECASE):
            entry.setdefault("website", re.search(r"(https?://|www\.)\S+", line, re.IGNORECASE)[0])
            continue
        phones = list(_SIG_PHONE.finditer(line))
        if phones and sum(c.isdigit() for c in line) >= 7:
            for m in phones:
                label = (m["label"] or "").lower()
                key = "whatsapp" if "whats" in label else "mobile" if label in ("mob", "mobile", "cell", "gsm", "m") \
                    else "phone"
                entry.setdefault(key, m["number"].strip())
                if m["ext"]:
                    entry.setdefault("extension", m["ext"])
            continue
        if "title" not in entry and classify(line) is not None:
            entry["title"] = line
        elif "company" not in entry:
            entry["company"] = line
    return entry if entry.get("email") or entry.get("mobile") or entry.get("phone") else None


def _entries(name: str, raw: bytes, columns: dict | None = None) -> tuple[list[dict], list[str]]:
    """(rows as {field: value}, the source's columns) of a contributed file. columns: a directory's (DIRECTORY_COLUMNS:
    the header row needs only a company column)."""
    lower = name.lower()
    if lower.endswith(".vcf"):
        cards = []
        for record in generic.vcard_records(raw.decode("utf-8", "replace")):
            if record.person:
                cards.append({"company": record.org[0], "person": record.person, "title": record.title,
                              "email": record.email, "mobile": record.phone,
                              "whatsapp": record.facts.get("whatsapp"),
                              "website": (record.domains or [None])[0]})
        return cards, ["vCard"]
    if lower.endswith((".txt", ".eml")):
        blocks = re.split(r"\n\s*\n|\n-{2,}\s*\n", raw.decode("utf-8", "replace"))
        return [e for e in (parse_signature(b) for b in blocks) if e], ["signature"]
    rows = [[generic._clean(c) for c in r] for r in (
        _html_rows(raw) if raw.lstrip()[:1] == b"<" else generic.xlsx_rows(raw) if lower.endswith((".xlsx", ".xls"))
        else generic.csv_rows(raw.decode("utf-8-sig", "replace")))]
    def is_header(m: dict) -> bool:
        if columns:
            return "company" in m
        return ("company" in m or "website" in m or "email" in m) and ("person" in m or "first_name" in m)

    header_at = next((i for i, r in enumerate(rows[:10]) if is_header(generic.header_map(r, columns or SEED_COLUMNS))),
                     None)
    if header_at is None:
        raise ValueError("no header row with a company name column" if columns else
                         "no header row with a contact name column and a company / website / e-mail column")
    mapping = generic.header_map(rows[header_at], columns or SEED_COLUMNS)
    # a directory's further columns of a multi-valued field ("Mobile 2", "Phone #3", a second "Executives"): joined
    # into the first one as 'a || b', the directory format directory_entries already splits
    extra: dict[str, list[int]] = {}
    if columns:
        for i, h in enumerate(rows[header_at]):
            bare = re.sub(r"[\s_#.-]*\d+$", "", h or "").strip()
            field = next((f for f in ("person", "mobile", "phone", "whatsapp", "email") if f in mapping
                          and i != mapping[f] and re.search(columns[f], bare, re.IGNORECASE)), None) if bare else None
            if field:
                extra.setdefault(field, []).append(i)
    out = []
    for row in rows[header_at + 1:]:
        entry = {f: row[i] for f, i in mapping.items() if i < len(row) and row[i]}
        for f, idx in extra.items():
            values = [entry[f]] if entry.get(f) else []
            values += [row[i] for i in idx if i < len(row) and row[i]]
            if values:
                entry[f] = " || ".join(values)
        if entry.get("first_name"):
            entry["person"] = " ".join(x for x in (entry.pop("first_name"), entry.get("last_name") or "") if x)
        elif entry.get("last_name") and entry.get("person"):
            entry["person"] = f"{entry['person']} {entry['last_name']}"
        out.append(entry)
    return out, rows[header_at]


def _html_rows(raw: bytes) -> list[list[str]]:
    """An HTML table saved as .xls (5INDEX's 'Excel' export): its rows' cell texts (stdlib parser, no download)."""
    from html.parser import HTMLParser

    class Table(HTMLParser):
        rows: list[list[str]] = []
        cell: list[str] | None = None

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self.rows.append([])
            elif tag in ("td", "th"):
                self.cell = []
            elif tag == "br" and self.cell is not None:
                self.cell.append(" ")

        def handle_startendtag(self, tag, attrs):  # 5INDEX writes '<td/>text</td>': a cell opening, not empty
            self.handle_starttag(tag, attrs)

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.cell is not None and self.rows:
                self.rows[-1].append("".join(self.cell))
                self.cell = None

        def handle_data(self, data):
            if self.cell is not None:
                self.cell.append(data)

    table = Table(convert_charrefs=True)
    table.rows = []
    table.feed(raw.decode("utf-8-sig", "replace"))
    return table.rows


def _labelled(text: str) -> tuple[str, str]:
    """'Mr. Ibrahim Sayah (Owner(s))' -> ('Mr. Ibrahim Sayah', 'Owner(s)'); '+961 03 - 777641 (Store)' -> number,
    label. The last balanced parenthesis is the label (titles nest: 'Owner(s)')."""
    text = text.strip()
    if text.endswith(")"):
        depth = 0
        for i in range(len(text) - 1, -1, -1):
            depth += {")": 1, "(": -1}.get(text[i], 0)
            if depth == 0:
                return text[:i].strip(), text[i + 1:-1].strip()
    return text, ""


def _lebanese(number: str) -> str:
    """'+961 03 - 777641' -> '+961 3 777641': the trunk 0 after the country code dropped."""
    return re.sub(r"^(\+|00)961[\s.-]*0", "+961 ", " ".join(number.replace(" - ", " ").split()))


def directory_entries(name: str, raw: bytes) -> tuple[list[dict], dict]:
    """A licensed directory export -> (entries, the columns: detected {field: header}, ignored, unrecognised, plus
    review notes). Cells may hold several values ('a || b'). Each file row gives one company entry (its contact
    points) and one entry per person (deduplicated by name, honorifics dropped; the most senior of their titles;
    their own numbers / e-mail):
      Executives  'Mr. X (Owner(s)) || Mr. X (Editor In Chief)': one person X, title Owner. A person column named
                  after a role ('General Manager', 'Gérant') is the title when the row states none.
      numbers     '+961 03 - 777641 (Mr. X)': X's number when X is one of the row's people; any other label
                  ('(Store)', '(Company)', a name not listed: noted for review) makes it the company's. Unlabelled:
                  a Mobile / a Lebanese mobile in Tel is the person's when the row names exactly one; else the
                  company's (its Tel is the company's line). WhatsApp stays WhatsApp.
      e-mails     a single named person's professional address is theirs; role mailboxes, free mail and every
                  address of a row naming several people are the company's.
    Rows without a company name (an ID only) are skipped quietly; placeholder cells ('N/A', '-', 'none') are empty,
    and a company row with no number, e-mail, website or person is skipped (counted in columns['no_data']). A row
    with people but no number, e-mail or website is 'weak': its people join a company LeadFinder already knows, but
    it never creates one (company_weak in the report)."""
    rows, header = _entries(name, raw, DIRECTORY_COLUMNS)
    mapping = generic.header_map(header, DIRECTORY_COLUMNS)
    role = header[mapping["person"]] if "person" in mapping and classify(header[mapping["person"]]) else None
    many = lambda v: [x.strip() for x in (v or "").split("||")  # noqa: E731
                      if x.strip() and not _PLACEHOLDER.match(_labelled(x)[0])]  # 'N/A (Store)': no number
    entries: list[dict] = []
    review: list[dict] = []
    no_data = 0
    for line, row in enumerate(rows, start=1):
        row = {k: v for k, v in row.items() if not _PLACEHOLDER.match(v)}
        if not row.get("company"):
            continue  # an empty record (ID only)
        if not any(many(row.get(k)) for k in ("phone", "mobile", "whatsapp", "email", "website", "person")):
            no_data += 1  # a name and nothing to reach it by: not worth a company
            continue
        rid = row.get("record_id")
        base = {k: row[k] for k in ("company", "sector", "city", "address", "registration_number") if row.get(k)}
        base |= {"country": row.get("country") or "Lebanon", "line": line}  # a Lebanese directory
        if not any(many(row.get(k)) for k in ("phone", "mobile", "whatsapp", "email", "website")):
            base["weak"] = True  # names only: adds people to a known company, never creates one
        if websites := many(row.get("website")):
            base["website"] = websites[0]
        people: dict[tuple, dict] = {}
        for item in many(row.get("person")):
            person, title = _labelled(item)
            person = _HONORIFIC.sub("", person).strip(" ,;-")
            if not (key := name_key(person)):
                continue
            p = people.setdefault(key, {"person": person, "titles": [], "phones": []})
            p["titles"].append(title or row.get("title") or role or "")
        company = {**base, "record_id": rid, "company_phones": [], "company_emails": []}
        sole = next(iter(people.values())) if len(people) == 1 else None
        for field, kind in (("phone", None), ("mobile", None), ("whatsapp", "whatsapp")):
            for item in many(row.get(field)):
                number, label = _labelled(item)
                number = _lebanese(number)
                owner = people.get(name_key(_HONORIFIC.sub("", label))) if label else None
                if owner is None and len(short := name_key(_HONORIFIC.sub("", label or ""))) >= 2:
                    # 'Minas Avakian' for 'Minas Antoun Avakian': the father's name left out (first + last, if unique)
                    same = [p for k, p in people.items() if len(k) >= 2 and (k[0], k[-1]) == (short[0], short[-1])]
                    owner = same[0] if len(same) == 1 else None
                if owner is None and not label and sole is not None and (field != "phone" or (
                        contacts.LEBANON_MOBILE.match(contacts.national(number) or "") and
                        not any(k != "whatsapp" for _, k in sole["phones"]))):
                    owner = sole
                if owner is not None:
                    owner["phones"].append((number, kind))
                    continue
                company["company_phones"].append((number, kind))
                folded = set(fold(label).split())
                if label and (_HONORIFIC.match(label) or len(folded) >= 2 and not folded & _NOT_A_PERSON):
                    review.append({"line": line, "company": row["company"],
                                   "reason": f"{field} labelled with a person who is not among the listed people: "
                                             "kept as the company's"})
        for item in many(row.get("email")):
            address = item.strip().lower()
            if sole is not None and "email" not in sole and not generic.ROLE_MAILBOX.match(address) and \
                    address.rpartition("@")[2] not in contacts.FREE_MAIL:
                sole["email"] = address
            else:
                company["company_emails"].append(address)
        entries.append(company)
        for p in people.values():
            ranked = sorted((t for t in p["titles"] if t), key=lambda t: (c.rank if (c := classify(t)) else 99))
            entries.append({**base, "person": p["person"], "title": ranked[0] if ranked else "",
                            "email": p.get("email"), "phones": p["phones"],
                            "record_id": f"{rid}:{' '.join(name_key(p['person']))}" if rid else None})
    used = set(mapping.values())
    return [{k: v for k, v in e.items() if v not in (None, "")} for e in entries], {
        "detected": {f: header[i] for f, i in mapping.items() if f != "fax"},
        "ignored": [header[mapping["fax"]]] if "fax" in mapping else [],
        "unrecognised": [h for i, h in enumerate(header) if h and i not in used], "review": review,
        "no_data": no_data}


# ---- resolution ------------------------------------------------------------------------------------------------------


class _Index:
    """Every LeadFinder company by verified domain, normalised name / alias and phone (built once per import)."""

    def __init__(self, db: Session):
        self.domains = {normalize_domain(d) or d: cid for cid, d in db.execute(
            select(Company.id, Company.domain).where(Company.domain.is_not(None)))}
        self.domains |= {normalize_domain(d) or d: cid for cid, d in db.execute(
            select(CompanyDomain.company_id, CompanyDomain.domain))}
        self.names: dict[str, set[int]] = {}
        self.phones: dict[str, set[int]] = {}
        self.country: dict[int, str | None] = {}
        for cid, name, legal, phone, country in db.execute(select(
                Company.id, Company.name, Company.legal_name, Company.primary_phone, Company.headquarters_country)):
            self.country[cid] = country
            for n in (name, legal):
                if n and (key := org_key(n)):
                    self.names.setdefault(key, set()).add(cid)
            if phone and (k := contacts.national(phone)):
                self.phones.setdefault(k, set()).add(cid)
        for cid, alias in db.execute(select(CompanyAlias.company_id, CompanyAlias.alias)):
            if alias and (key := org_key(alias)):
                self.names.setdefault(key, set()).add(cid)

    def match(self, entry: dict, email: str | None) -> tuple[str, int | None]:
        domains = [d for d in ((generic._domains_of(entry.get("website")) or [None])[0],
                               (email or "").rpartition("@")[2] or None) if d and d not in contacts.FREE_MAIL]
        for d in domains:
            if (cid := self.domains.get(normalize_domain(d) or d)) is not None:
                return "exact", cid
        country = entry.get("country")

        def compatible(cid: int) -> bool:  # a country that disagrees rules a candidate out
            theirs = self.country.get(cid)
            if not country or not theirs:
                return True
            a, b = find_country(country), find_country(theirs)
            return a.code == b.code if a and b else fold(country) == fold(theirs)

        named = {c for c in self.names.get(org_key(entry.get("company") or ""), set()) if compatible(c)}
        if len(named) == 1:
            return "strong", next(iter(named))
        phoned = {c for c in self.phones.get(contacts.national(entry.get("company_phone")) or "-", set())
                  if compatible(c)}
        if len(phoned) == 1:
            return "strong", next(iter(phoned))
        return ("possible", None) if len(named) > 1 or len(phoned) > 1 else ("unmatched", None)

    def add(self, company: Company, domain: str | None) -> None:  # a company this import created
        self.country[company.id] = company.headquarters_country
        if key := org_key(company.name):
            self.names.setdefault(key, set()).add(company.id)
        if domain:
            self.domains[domain] = company.id
        if company.primary_phone and (k := contacts.national(company.primary_phone)):
            self.phones.setdefault(k, set()).add(company.id)


def _create_company(db: Session, entry: dict, index: _Index, *, user_id: int | None, import_id: str | None,
                    stated: datetime, directory: str) -> tuple[str, int | None, str | None]:
    """A licensed directory's company LeadFinder lacks -> discovery's own pipeline: validation, duplicate
    resolution (the same record, registration number, domain, phone + name, name + city: an existing company is
    reused; a deleted one is never re-created; a weak match is recorded as a possible duplicate) and persistence (the
    company, its source and evidence). (level, company id, why not)."""
    from app.services.discovery.candidate import CompanyCandidate, ConnectorConfig
    from app.services.discovery.consolidation import assess, consolidate
    from app.services.discovery.deduplication import resolve as resolve_company
    from app.services.discovery.industries import AnyBusinessProfile, label_nodes
    from app.services.discovery.normalizer import normalize, validate
    from app.services.discovery.orchestrator import _LOCK_KEY
    from app.services.discovery.persistence import save

    country = find_country(entry.get("country") or "Lebanon") or find_country("Lebanon")
    name = f"{directory} (licensed directory)"
    key = f"{fold(directory)}:" + (entry.get("record_id") or hashlib.sha256("|".join(
        fold(entry.get(k) or "") for k in ("company", "city")).encode()).hexdigest()[:32])
    c = validate(CompanyCandidate(
        connector="licensed_directory", source_name=name, source_type="licensed_directory",
        company_name=entry["company"], external_id=key[:300], observed_at=stated, website=entry.get("website"),
        phone=entry.get("company_phone"), city=entry.get("city"), address=entry.get("address"),
        industry=entry.get("sector"), categories=sorted(label_nodes([entry["sector"]])) if entry.get("sector") else [],
        registration_number=entry.get("registration_number"),
        raw_metadata={"import_id": import_id, "directory": directory}))
    if c.rejected:
        return "rejected", None, c.reject_reason
    group = consolidate([c])[0]
    norms = {id(c): normalize(c, country, AnyBusinessProfile())}
    db.execute(select(func.pg_advisory_xact_lock(_LOCK_KEY)))  # one resolve-and-create at a time (discovery's)
    found = resolve_company(db, group, norms, country.code)
    if found.suppressed:
        return "deleted", None, found.suppressed
    if found.company is not None:
        return "strong", found.company.id, None
    norms[id(c)].phone = None  # its Tel is stored below as a licensed contact point, not a public one
    config = ConnectorConfig(key="licensed_directory", kind="dataset_file", enabled=True, countries=(), priority=0,
                             source_type="licensed_directory", quality=DIRECTORY_QUALITY, label=name)
    company, _ = save(db, group=group, norms=norms, resolution=found, assessment=assess(group), country=country,
                      configs={"licensed_directory": config}, versions={}, user_id=user_id)
    db.flush()
    index.add(company, norms[id(c)].domain)
    from app.services.enrichment import orchestrator as enrichment

    # researched in the background (website, then people), after anything a user is looking at; a dry run rolls back
    enrichment.request(db, company, enrichment.STALE, user_id=user_id)
    return "created", company.id, None


def _phone(raw: str | None, country: str | None) -> tuple[str, str | None] | None:
    """(as given, E.164 when the country is known or the number carries its own code: never an assumed code)."""
    if not raw:
        return None
    return raw, normalize_phone(raw, country) if (country or raw.strip().startswith(("+", "00"))) else None


def _known_person(db: Session, company_id: int, email: str | None, name: str | None) -> int | None:
    """A person LeadFinder already knows at the company: the same work e-mail, else exactly one same name."""
    if email and (pid := db.scalar(select(Email.person_id).where(Email.email == email,
                                                                 Email.company_id == company_id))):
        return pid
    key = name_key(name or "")
    same = {p.id for p in db.scalars(select(Person).join(CompanyPerson).where(CompanyPerson.company_id == company_id))
            if key and name_key(p.full_name) == key}
    return next(iter(same)) if len(same) == 1 else None


# ---- the pipeline ----------------------------------------------------------------------------------------------------


def contribute(db: Session, entries: list[dict], *, channel: str, contributor_id: int | None = None,
               visibility: str = "organization", apply: bool = False, label: str = "contribution",
               company_id: int | None = None, import_id: str | None = None, directory: str = "Other") -> dict:
    """Entries -> the contact graph. company_id: the entries are this company's (a contribution made on its page).
    import_id: tags every source of this run (remove_import); directory: the licensed directory's name. The report
    is exactly what an apply does; it is written only when apply=True (a dry run rolls back)."""
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {', '.join(CHANNELS)}")
    if visibility not in VISIBILITIES:
        raise ValueError(f"visibility must be one of {', '.join(VISIBILITIES)}")
    source_type, provenance, all_confirmed = CHANNELS[channel]
    licensed = channel == LICENSED
    now = datetime.now(timezone.utc)
    index = _Index(db) if company_id is None else None
    users = {key.lower(): u.id for u in db.scalars(select(User)) for key in (u.email, u.name) if key}  # Odoo: names
    stats: Counter = Counter()
    review: list[dict] = []
    companies, people_seen, created, lines, imported = set(), set(), set(), set(), set()
    for n, entry in enumerate(entries, start=1):
        if not entry:
            continue
        line = entry.get("line", n)  # a directory row gives several entries (its company, its people)
        lines.add(line)
        email = (generic._EMAIL.findall(entry.get("email") or "") or [None])[0]
        email = email.strip().lower() if email else None
        if email and generic.ROLE_MAILBOX.match(email):
            email = None  # info@ / sales@: never a person's
        stated = published_date(entry.get("last_seen")) or now
        level, cid = ("given", company_id) if company_id else index.match(entry, email)
        why = None
        if cid is None and licensed and level == "unmatched" and entry.get("weak"):
            level, why = "weak", "no phone, e-mail or website: not added as a new company"
        elif cid is None and licensed and level == "unmatched" and entry.get("company"):
            level, cid, why = _create_company(db, entry, index, user_id=contributor_id, import_id=import_id,
                                              stated=stated, directory=directory)
            created.update([cid] if level == "created" else [])
        stats[f"company_{level}"] += 1
        if cid is None:
            if len(review) < 100:
                review.append({"line": line, "company": entry.get("company"), "reason": why or f"company {level}"})
            continue
        company = db.get(Company, cid)
        country = entry.get("country") or company.headquarters_country
        owner = users.get((entry.get("owner") or "").lower(), contributor_id)
        record_id = entry.get("record_id") or "|".join(fold(entry.get(k) or "") for k in ("person", "email"))
        record_id = f"{fold(directory)}:{record_id}" if licensed else record_id  # one source per directory
        source = db.scalar(select(Source).where(Source.source_type == source_type, Source.publisher == channel,
                                                Source.external_reference == f"{cid}:{record_id}"[:300]))
        if source is not None and (source.metadata_ or {}).get("suppressed"):
            stats["suppressed_skipped"] += 1  # removed on request: never imported again
            continue
        stats["source_records_seen_before" if source else "source_records_new"] += 1
        if source is None:
            source = Source(source_type=source_type, name=f"{directory} (licensed directory)" if licensed else
                            f"TECOMSA {channel.replace('_', ' ').title()}",
                            publisher=channel, external_reference=f"{cid}:{record_id}"[:300], retrieved_at=now,
                            published_at=stated, source_quality=DIRECTORY_QUALITY if licensed else 95,
                            metadata_={"contributor_user_id": owner, "visibility": visibility, "label": label,
                                       "channel": channel, "contributed_at": now.isoformat(),
                                       **({"directory": directory} if licensed else {})})
            db.add(source)
            db.flush()
        meta = source.metadata_ or {}
        if import_id and import_id not in meta.get("imports", []):
            source.metadata_ = {**meta, "imports": [*meta.get("imports", []), import_id]}
        if licensed:
            companies.add(cid)
            imported.add(line)
            _company_contacts(db, entry, company, country, source, owner, visibility, provenance, stated, stats)
            if not entry.get("person"):
                continue  # the row's company entry: its contact points are the company's
        title = entry.get("title") or ""
        if entry.get("department") and title and fold(entry["department"]) not in fold(title):
            title = f"{title}, {entry['department']}"
        if not title:  # attendance / a card without a title: contacts of a person already known, never a new one
            person_id = _known_person(db, cid, email, entry.get("person"))
            if person_id is None:
                stats["rejected_no_title_unknown_person"] += 1
                if len(review) < 100:
                    review.append({"line": line, "company": company.name, "person": entry.get("person"),
                                   "reason": "no job title and not a known person: not created"})
                continue
            stats["person_exact"] += 1
        else:
            status = "former" if FORMER.match(entry.get("employment") or "") else None
            record = Record(org=[company.name], person=entry.get("person"), title=title, email=email, status=status,
                            published=stated.date().isoformat(), excerpt=f"{channel} record {record_id}")
            c = candidate(record, company_id=cid, source_id=source.id, url=None, source_type="internal",
                          quality=95, match_confidence=95, stated=stated, category=source_type, document=label)
            if c is None:
                stats["rejected_not_person_or_title"] += 1
                if len(review) < 100:
                    review.append({"line": line, "company": company.name, "reason": "no person name / job title"})
                continue
            c.email = c.phone = None  # stored below with this channel's provenance
            same = _known_person(db, cid, email, None) or db.scalar(select(CompanyPerson.person_id).join(
                Evidence, Evidence.company_person_id == CompanyPerson.id).where(Evidence.source_id == source.id)
                .limit(1))
            match = resolve(db, cid, c)
            if same is not None:
                match = Match(db.get(Person, same), "same work e-mail / same contributed record")
                stats["person_exact"] += 1
            elif match.person is not None:
                stats["person_strong"] += 1
            elif match.possible:
                stats["person_possible"] += 1
                if len(review) < 100:
                    review.append({"line": line, "company": company.name, "person": c.full_name,
                                   "reason": f"possibly {match.possible[0].full_name} (another role): review"})
                continue
            else:
                stats["person_new"] += 1
            confirmed = [r for r in db.scalars(select(CompanyPerson).where(
                CompanyPerson.company_id == cid, CompanyPerson.person_id == match.person.id))
                if "job_title" in (r.corrected_fields or [])] if match.person else []
            if confirmed and all(fold(r.job_title) != fold(c.raw_title or "") for r in confirmed):
                stats["conflicts"] += 1  # a colleague-confirmed title outranks the contribution: flagged, kept
                if len(review) < 100:
                    review.append({"line": line, "company": company.name, "person": c.full_name,
                                   "reason": f"title conflict: confirmed '{confirmed[0].job_title}' vs "
                                             f"'{c.raw_title}' (not changed)"})
                person_id = match.person.id
            else:
                known = set(db.scalars(select(CompanyPerson.id).where(CompanyPerson.company_id == cid)))
                role = persistence.save(db, company, c, match, now)
                if role is None:
                    stats["suppressed_person"] += 1  # removed on request: never imported again
                    continue
                if role.id not in known:  # only a role the contribution creates is TECOMSA's (public stays public)
                    role.owner_user_id, role.visibility = owner, visibility
                person_id = role.person_id
        companies.add(cid)
        people_seen.add(person_id)
        stats[f"visibility_{visibility}"] += 1
        _contacts(db, entry, email, person_id, company, country, source, owner, visibility, provenance,
                  all_confirmed, record_id, channel, stated, stats)
        persistence.recompute(db, company)
    if lines:
        stats["rows"] = len(lines)
    if licensed:
        stats["rows_imported"] = len(imported)
    report = {**dict(stats), "companies_matched": len(companies), "unique_people": len(people_seen),
              "review": review, "applied": apply, "channel": channel, "label": label}
    if licensed:
        report["companies_created"], report["directory"] = len(created), directory
    if apply:
        audit_service.record(db, action="contribution.applied", user_id=contributor_id, entity_type="contribution",
                             entity_id=(import_id or label)[:100],
                             metadata={**{k: v for k, v in report.items() if k != "review"},
                                       **({"created_company_ids": sorted(created)} if created else {})})
        db.commit()
    else:
        db.rollback()  # a dry run: exactly what an apply would do, nothing written
    logger.info("contribution %s %s (%s): %s", channel, label, "applied" if apply else "dry run",
                {k: v for k, v in report.items() if k != "review"})
    return report


def ingest(db: Session, *, system: str, file_name: str, raw: bytes, owner_user_id: int | None = None,
           visibility: str = "organization", apply: bool = False, user_id: int | None = None) -> dict:
    """A contributed file (CSV / XLSX rows, .vcf cards, .txt signatures) through the pipeline."""
    entries, columns = _entries(file_name, raw)
    report = contribute(db, entries, channel=system, contributor_id=owner_user_id, visibility=visibility,
                        apply=apply, label=file_name)
    return {**report, "file": file_name, "columns": columns}


def import_directory(db: Session, *, file_name: str, raw: bytes, directory: str, user_id: int | None = None,
                     visibility: str = "organization", apply: bool = False) -> dict:
    """A licensed directory export (CSV / XLSX; directory: 5INDEX, Yelleb...) through the pipeline: dry run unless
    apply. The report adds
    the detected columns, a summary (the counts the import screen shows) and, when applied, the import's id."""
    directory = " ".join((directory or "").split())[:60]
    if not directory:
        raise ValueError("name the directory the file comes from")
    entries, columns = directory_entries(file_name, raw)
    import_id = uuid.uuid4().hex[:16]
    report = contribute(db, entries, channel=LICENSED, contributor_id=user_id, visibility=visibility, apply=apply,
                        label=file_name, import_id=import_id, directory=directory)
    notes = columns.pop("review")
    if no_data := columns.pop("no_data"):  # skipped rows: counted in rows / rows_skipped
        report["rows"] = report.get("rows", 0) + no_data
        report["rows_no_data"] = no_data
    report["review"] = (notes + report["review"])[:100]
    report["numbers_of_unlisted_people"] = len(notes)
    return {**report, "file": file_name, "columns": columns, "summary": summary(report),
            "import_id": import_id if apply else None}


def summary(report: dict) -> dict:
    """What a directory import adds: companies (new / already known), people, mobiles, WhatsApp, other numbers,
    e-mails,
    the rows skipped (no company could be resolved or created: see the review)."""
    g = lambda k: report.get(k, 0)  # noqa: E731
    mobiles = g("phones_added_business_mobile") + g("company_phones_added_business_mobile")
    whatsapp = g("phones_added_whatsapp") + g("company_phones_added_whatsapp")
    return {"rows": g("rows"), "companies_new": g("companies_created"),
            "companies_existing": g("companies_matched") - g("companies_created"), "people": g("unique_people"),
            "people_new": g("person_new"), "mobiles": mobiles, "whatsapp": whatsapp,
            "phones": g("phones_added") + g("company_phones_added") - mobiles - whatsapp,
            "emails": g("emails_added") + g("company_emails_added"), "rows_skipped": g("rows") - g("rows_imported")}


def coverage(db: Session) -> list[dict]:
    """Per licensed directory, what it states today (whether another source also states it or not): people (with a
    role), people with a mobile / a WhatsApp number / an e-mail, companies with a number. Compares directories."""
    name = Source.metadata_["directory"].astext
    mine = (Source.source_type == "licensed_directory", Source.publisher == LICENSED)
    out: dict[str, dict] = {}

    def count(key: str, column, *join_where) -> None:
        stmt = select(name, func.count(func.distinct(column))).select_from(Source)
        for target, on in join_where[:-1]:
            stmt = stmt.join(target, on)
        for d, n in db.execute(stmt.where(*mine, join_where[-1]).group_by(name)):
            out.setdefault(d or "Other", {})[key] = n

    phone = ((ContactEvidence, ContactEvidence.source_id == Source.id), (Phone, Phone.id == ContactEvidence.phone_id))
    count("people", CompanyPerson.person_id, (Evidence, Evidence.source_id == Source.id),
          (CompanyPerson, CompanyPerson.id == Evidence.company_person_id),
          Evidence.company_person_id.is_not(None))
    count("people_with_mobile", Phone.person_id, *phone, Phone.phone_type == "business_mobile")
    count("people_with_whatsapp", Phone.person_id, *phone, Phone.phone_type == "whatsapp")
    count("people_with_email", Email.person_id, (ContactEvidence, ContactEvidence.source_id == Source.id),
          (Email, Email.id == ContactEvidence.email_id), Email.person_id.is_not(None))
    count("companies_with_number", Phone.company_id, *phone, Phone.person_id.is_(None))
    keys = ("people", "people_with_mobile", "people_with_whatsapp", "people_with_email", "companies_with_number")
    return [{"directory": d, **{k: row.get(k, 0) for k in keys}} for d, row in sorted(out.items())]


def imports(db: Session, limit: int = 50) -> list[dict]:
    """The directory imports applied, newest first (from the audit trail), each with its summary and whether it
    was removed."""
    removed = dict(db.execute(select(AuditLog.entity_id, AuditLog.created_at).where(
        AuditLog.action == "contribution.import_removed")).all())
    rows = db.scalars(select(AuditLog).where(AuditLog.action == "contribution.applied",
                                             AuditLog.metadata_["channel"].astext == LICENSED)
                      .order_by(AuditLog.id.desc()).limit(limit))
    return [{"import_id": r.entity_id, "file": (r.metadata_ or {}).get("label"), "created_at": r.created_at,
             "directory": (r.metadata_ or {}).get("directory"),
             "user": r.user.name if r.user else None, "summary": summary(r.metadata_ or {}),
             "removed_at": removed.get(r.entity_id)} for r in rows]


def _contacts(db: Session, entry: dict, email: str | None, person_id: int, company: Company, country: str | None,
              source: Source, owner: int | None, visibility: str, provenance: str, all_confirmed: bool,
              record_id: str, channel: str, stated: datetime, stats: Counter) -> None:
    evidence = f"TECOMSA {channel} record {record_id}"[:500]
    status_text = entry.get("contact_status") or ""
    if email:
        status = "confirmed" if all_confirmed or CONFIRMED.match(status_text) else \
            "invalid" if INVALID.match(status_text) else "published"
        row = db.scalar(select(Email).where(Email.person_id == person_id, Email.email == email))
        if row is None:
            row = Email(person_id=person_id, company_id=company.id, email=email, email_type="work", status=status,
                        confidence=95 if status != "invalid" else 0, source_id=source.id, first_seen_at=stated,
                        last_seen_at=stated, provenance=provenance, owner_user_id=owner, visibility=visibility,
                        evidence=evidence, last_verified_at=stated if status == "confirmed" else None)
            db.add(row)
            stats["emails_added"] += 1
            stats["emails_confirmed"] += status == "confirmed"
        else:
            stats["emails_already_known"] += 1  # a duplicate avoided: its evidence is added, the row kept
            others = set(db.scalars(select(ContactEvidence.source_id).where(ContactEvidence.email_id == row.id)))
            if source.id not in others:
                stats["emails_corroborated"] += 1  # another source states the same address
                row.confidence = min(95, (row.confidence or 60) + 5)
            if row.status in WEAK_STATUSES and status != "invalid":
                stats["predicted_to_corroborated"] += row.status != "unknown"
                row.status, row.provenance, row.last_verified_at = status, provenance, (
                    stated if status == "confirmed" else None)  # a real record attests the guess
            elif status == "confirmed" and row.status != "confirmed" and row.provenance != "human_confirmed":
                row.status, row.last_verified_at, row.confidence = "confirmed", stated, 95
                stats["emails_confirmed"] += 1
            row.last_seen_at = max(row.last_seen_at or stated, stated)
        db.flush()
        if not db.scalar(select(ContactEvidence.id).where(ContactEvidence.email_id == row.id,
                                                          ContactEvidence.source_id == source.id)):
            db.add(ContactEvidence(email_id=row.id, kind=f"{channel.lower()}_{status}", source_id=source.id,
                                   user_id=owner, detail=evidence[:300], observed_at=stated))
    for raw, kind in entry.get("phones") or ((entry.get("mobile"), "business_mobile"),
                                             (entry.get("whatsapp"), "whatsapp"), (entry.get("phone"), None)):
        parsed = _phone(raw, country)
        if not parsed:
            continue
        given, number = parsed
        if entry.get("extension") and kind is None:
            given, kind = f"{given} ext. {entry['extension']}", "office_extension"
        if number and contacts.national(number) in {contacts.national(company.primary_phone)} - {None}:
            stats["phones_company_line_skipped"] += 1  # the company's main line is never the person's number
            continue
        kind = kind or contacts.classify_phone(number or given, company_numbers=set(), context=given)
        existing = db.scalar(select(Phone).where(Phone.person_id == person_id, (
            Phone.normalized_phone == number) if number else (Phone.phone == given)))
        if existing is None:
            existing = Phone(person_id=person_id, company_id=company.id, phone=given[:50], normalized_phone=number,
                             phone_type=kind, confidence=95, source_id=source.id, first_seen_at=stated,
                             last_seen_at=stated, provenance=provenance, owner_user_id=owner, visibility=visibility,
                             evidence=evidence)
            db.add(existing)
            stats["phones_added"] += 1
            stats[f"phones_added_{kind}"] += 1
            stats["phones_without_country_code"] += number is None
        else:
            stats["phones_already_known"] += 1
            if source.id not in set(db.scalars(select(ContactEvidence.source_id).where(
                    ContactEvidence.phone_id == existing.id))):
                stats["phones_corroborated"] += 1
        db.flush()
        if not db.scalar(select(ContactEvidence.id).where(ContactEvidence.phone_id == existing.id,
                                                          ContactEvidence.source_id == source.id)):
            db.add(ContactEvidence(phone_id=existing.id, kind=channel.lower(), source_id=source.id, user_id=owner,
                                   detail=evidence[:300], observed_at=stated))


def _company_contacts(db: Session, entry: dict, company: Company, country: str | None, source: Source,
                      owner: int | None, visibility: str, provenance: str, stated: datetime, stats: Counter) -> None:
    """A directory row's company contact points: its Tel (the switchboard; a mobile number stays a mobile), the
    mobile / WhatsApp of a row naming nobody, its role mailbox / an e-mail no person is named for. Blank primary phone /
    e-mail completed; one row per number / address (evidence added when already known)."""
    evidence = f"{source.name} record {source.external_reference}"[:500]
    for (given, number), kind in ((p, k) for raw, k in entry.get("company_phones", []) if (p := _phone(raw, country))):
        kind = kind or ("business_mobile" if contacts.LEBANON_MOBILE.match(contacts.national(number or given) or "")
                        else "company_switchboard")
        row = db.scalar(select(Phone).where(Phone.company_id == company.id, Phone.person_id.is_(None), (
            Phone.normalized_phone == number) if number else (Phone.phone == given)).limit(1))
        if row is None:
            row = Phone(company_id=company.id, phone=given[:50], normalized_phone=number, phone_type=kind,
                        confidence=DIRECTORY_QUALITY, source_id=source.id, first_seen_at=stated, last_seen_at=stated,
                        provenance=provenance, owner_user_id=owner, visibility=visibility, evidence=evidence)
            db.add(row)
            db.flush()
            stats["company_phones_added"] += 1
            stats[f"company_phones_added_{kind}"] += 1
        else:
            stats["company_phones_already_known"] += 1
        if kind == "company_switchboard" and not company.primary_phone:
            company.primary_phone = given[:50]
        if not db.scalar(select(ContactEvidence.id).where(ContactEvidence.phone_id == row.id,
                                                          ContactEvidence.source_id == source.id)):
            db.add(ContactEvidence(phone_id=row.id, kind=LICENSED.lower(), source_id=source.id, user_id=owner,
                                   detail=evidence[:300], observed_at=stated))
    for email in dict.fromkeys(e for raw in entry.get("company_emails", [])
                               for e in generic._EMAIL.findall(raw.lower())):
        row = db.scalar(select(Email).where(Email.company_id == company.id, Email.person_id.is_(None),
                                            Email.email == email))
        if row is None:
            row = Email(company_id=company.id, email=email, email_type="generic", status="published",
                        confidence=DIRECTORY_QUALITY, source_id=source.id, first_seen_at=stated, last_seen_at=stated,
                        provenance=provenance, owner_user_id=owner, visibility=visibility, evidence=evidence)
            db.add(row)
            db.flush()
            stats["company_emails_added"] += 1
        else:
            stats["company_emails_already_known"] += 1
        company.primary_email = company.primary_email or email
        if not db.scalar(select(ContactEvidence.id).where(ContactEvidence.email_id == row.id,
                                                          ContactEvidence.source_id == source.id)):
            db.add(ContactEvidence(email_id=row.id, kind=LICENSED.lower(), source_id=source.id, user_id=owner,
                                   detail=evidence[:300], observed_at=stated))


# ---- connectors ------------------------------------------------------------------------------------------------------


class BusinessContactConnector:
    """A source of explicitly authorized business-contact intelligence (a CRM, a mail / calendar account a user
    connected on purpose). Connector-neutral: an implementation only returns plain entries / events; LeadFinder's
    rules (resolution, provenance, visibility, feedback) stay here. None is configured: no credentials exist yet."""

    channel_contacts = "CONTRIBUTED_BUSINESS_CONTACT"

    def business_contacts(self) -> list[dict]:  # CRM / address-book business contacts the user authorized
        return []

    def meeting_participants(self) -> list[dict]:  # {person, email, company / website, last_seen (meeting date)}
        return []

    def signatures(self) -> list[str]:  # signature blocks of business e-mails the user chose to share
        return []

    def delivery_events(self) -> list[dict]:  # {event: delivered / hard_bounce / soft_bounce / replied, email, event_key}
        return []


def sync(db: Session, connector: BusinessContactConnector, user: User, *, visibility: str = "managers",
         apply: bool = False) -> dict:
    """One connector's authorized data through the same pipeline (dry run unless apply) and its mail events through
    the feedback rules (applied once per event key; only when apply)."""
    from app.services import contact_feedback

    report = {
        "contacts": contribute(db, connector.business_contacts(), channel=connector.channel_contacts,
                               contributor_id=user.id, visibility=visibility, apply=apply, label="connector"),
        "meetings": contribute(db, connector.meeting_participants(), channel="MEETING_CONTACT",
                               contributor_id=user.id, visibility=visibility, apply=apply, label="connector"),
        "signatures": contribute(db, [e for e in map(parse_signature, connector.signatures()) if e],
                                 channel="EMAIL_SIGNATURE", contributor_id=user.id, visibility=visibility, apply=apply,
                                 label="connector"),
    }
    events = connector.delivery_events()
    report["events_applied"] = sum(contact_feedback.record_email_event(
        db, user, e["email"], e["event"], event_key=e.get("event_key")) for e in events) if apply else 0
    report["events_received"] = len(events)
    return report


# ---- removal ---------------------------------------------------------------------------------------------------------


def suppress(db: Session, source_id: int, *, user_id: int | None, reason: str) -> dict:
    """Remove one contributed / internal source's contribution (a correction, a deletion request, a retention
    rule): its evidence goes; a contact or role known ONLY from it goes; anything another source also states (public
    evidence included) stays. The source is kept, marked suppressed, and never imported again."""
    source = db.get(Source, source_id)
    channels = {t for t, _, _ in CHANNELS.values()}
    if source is None or source.source_type not in channels:
        raise ValueError("not a contributed / internal source")
    removed = _remove(db, source_id)
    source.metadata_ = {**(source.metadata_ or {}), "suppressed": True, "suppressed_reason": reason[:300],
                        "suppressed_at": datetime.now(timezone.utc).isoformat()}
    audit_service.record(db, action="contribution.suppressed", user_id=user_id, entity_type="source",
                         entity_id=source_id, metadata={"reason": reason, **removed})
    db.commit()
    return dict(removed)


def remove_import(db: Session, import_id: str, *, user_id: int | None) -> dict:
    """Delete one directory import (a wrong file, the end of the licence): what only it stated goes (contacts, roles,
    the companies it created that nothing else describes); what another source or import also states stays. Not a
    suppression: the same records can be imported again."""
    applied = db.scalar(select(AuditLog).where(AuditLog.action == "contribution.applied",
                                               AuditLog.entity_id == import_id))
    if applied is None or (applied.metadata_ or {}).get("channel") != LICENSED:
        raise LookupError("no such import")
    if db.scalar(select(AuditLog.id).where(AuditLog.action == "contribution.import_removed",
                                           AuditLog.entity_id == import_id)):
        raise ValueError("this import was already removed")
    removed: Counter = Counter()
    for source in db.scalars(select(Source).where(Source.metadata_["imports"].contains([import_id]))).all():
        left = [i for i in source.metadata_["imports"] if i != import_id]
        source.metadata_ = {**source.metadata_, "imports": left}
        if not left:  # no other import states these records
            removed.update(_remove(db, source.id))
    db.flush()
    created = {cid for meta in db.scalars(select(AuditLog.metadata_).where(
        AuditLog.action == "contribution.applied", AuditLog.metadata_["channel"].astext == LICENSED))
        for cid in (meta or {}).get("created_company_ids", [])}  # by this import or an earlier one
    other = select(Source.id).where(Source.source_type != "licensed_directory")
    for cid in sorted(created):
        if db.get(Company, cid) is None:
            continue
        roles = select(CompanyPerson.id).where(CompanyPerson.company_id == cid)
        if db.scalar(select(func.count()).select_from(Evidence).where(
                or_(Evidence.company_id == cid, Evidence.company_person_id.in_(roles)), Evidence.source_id.in_(other))
                ) or db.scalar(roles.limit(1)) or db.scalar(select(Source.id).where(
                Source.publisher == LICENSED, Source.external_reference.like(f"{cid}:%"),
                func.jsonb_array_length(Source.metadata_["imports"]) > 0).limit(1)):
            removed["companies_kept"] += 1  # another import still lists it / researched or known elsewhere since
            continue
        for model in (Email, Phone):
            db.execute(delete(model).where(model.company_id == cid, model.person_id.is_(None)))
        db.delete(db.get(Company, cid))
        removed["companies_removed"] += 1
    audit_service.record(db, action="contribution.import_removed", user_id=user_id, entity_type="contribution",
                         entity_id=import_id, metadata={"file": applied.metadata_.get("label"), **removed})
    db.commit()
    return dict(removed)


def _remove(db: Session, source_id: int) -> Counter:
    """One source's contribution removed: its evidence goes; a contact or role known ONLY from it goes."""
    removed = Counter()
    for model, column in ((Email, ContactEvidence.email_id), (Phone, ContactEvidence.phone_id)):
        ids = set(db.scalars(select(column).where(ContactEvidence.source_id == source_id, column.is_not(None))))
        for row in db.scalars(select(model).where(model.id.in_(ids or {0}))).all():
            others = set(db.scalars(select(ContactEvidence.source_id).where(column == row.id))) - {source_id}
            if not others and row.provenance in ("internal_crm", "contributed", "human_confirmed", "licensed"):
                db.delete(row)
                removed[f"{model.__tablename__}_removed"] += 1
            else:
                for ev in db.scalars(select(ContactEvidence).where(column == row.id,
                                                                   ContactEvidence.source_id == source_id)):
                    db.delete(ev)
                removed[f"{model.__tablename__}_kept_other_evidence"] += 1
    for role in db.scalars(select(CompanyPerson).join(Evidence, Evidence.company_person_id == CompanyPerson.id)
                           .where(Evidence.source_id == source_id).distinct()).all():
        sources = set(db.scalars(select(Evidence.source_id).where(Evidence.company_person_id == role.id)))
        if sources == {source_id}:
            db.delete(role)
            removed["roles_removed"] += 1
        else:
            for ev in db.scalars(select(Evidence).where(Evidence.company_person_id == role.id,
                                                        Evidence.source_id == source_id)):
                db.delete(ev)
            removed["roles_kept_other_evidence"] += 1
    return removed


if __name__ == "__main__":
    import argparse
    import json

    from app.db.session import SessionLocal

    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("channel", choices=SYSTEMS)
    parser.add_argument("--owner", help="the e-mail of the LeadFinder user contributing / owning these contacts")
    parser.add_argument("--visibility", choices=VISIBILITIES, default="organization")
    parser.add_argument("--directory", default="5INDEX", help=f"LICENSED_DIRECTORY: {', '.join(DIRECTORIES)}, ...")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args()
    with SessionLocal() as session, open(args.file, "rb") as f:
        owner_id = session.scalar(select(User.id).where(User.email == args.owner)) if args.owner else None
        if args.channel == LICENSED:  # a big directory export: listed (and removable) in the app's import history
            import os

            result = import_directory(session, file_name=os.path.basename(args.file), raw=f.read(), user_id=owner_id,
                                      directory=args.directory, visibility=args.visibility, apply=args.apply)
        else:
            result = ingest(session, system=args.channel, file_name=args.file, raw=f.read(), owner_user_id=owner_id,
                            visibility=args.visibility, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
