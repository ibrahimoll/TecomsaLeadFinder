"""Generic people / contact extraction for source-to-many ingestion (Step 6.1): any table (HTML, XLSX / XLS, CSV), a
Word document (.docx) or business cards (.vcf) -> Records (organisation + person + title + business e-mail / phone /
mobile / WhatsApp), then the source pack's local matching (pack.apply) attaches them to every LeadFinder company.

Tables: the header row is found automatically ("Company / Exhibitor", "Contact person / Name", "Position / Title",
"E-mail", "Mobile", "WhatsApp"...; English, French, Arabic) unless the source's `columns` say otherwise.
Contact ownership: a row's e-mail / phone belongs to its PERSON only when the row names one AND it is not a role
mailbox (info@, sales@...); otherwise it is the company's (a fact, never a person's). Nothing is inferred: only what
the row states.
"""

import csv
import io
import re
import zipfile

from app.services.people.external.lebanon.records import Record

DEFAULT_COLUMNS = {
    "company": r"^(?:company|company name|exhibitor|organi[sz]ation|firm|establishment|member|institution|"
               r"employer|account|soci[eé]t[eé]|entreprise|الشركة|المؤسسة|اسم الشركة)\b",
    "person": r"^(?:(?:contact|key)?\s*(?:person|name|full name|contact name|representative)|speaker|panelist|"
              r"first name|nom|الاسم|اسم)\b",
    "last_name": r"^(?:last name|surname|family name|nom de famille)\b",
    "title": r"^(?:title|job title|job position|job function|position|designation|role|function|fonction|poste|"
             r"المنصب|الوظيفة)\b",
    "department": r"^(?:department|dept|division|d[eé]partement|القسم)\b",
    "email": r"(?:e-?mail|courriel|البريد)",
    "mobile": r"(?:mobile|cell|gsm|portable|الخلوي|الجوال)",
    "whatsapp": r"whats\s?app",
    "phone": r"^(?:phone|tel|telephone|t[eé]l[eé]phone|landline|office|direct|الهاتف)\b",
    "website": r"(?:website|web site|url|site web|الموقع)",
    "sector": r"^(?:sector|activity|industry|category|secteur|القطاع)\b",
    "city": r"^(?:city|town|ville|المدينة)\b",
    "country": r"^(?:country|pays|البلد)\b",
    "booth": r"^(?:booth|stand|hall)\b",
}
ROLE_MAILBOX = re.compile(r"^(info|contact|contactus|sales|export|office|admin|hello|enquir\w*|inquir\w*|marketing|"
                          r"support|mail|general|reception|customerservice|cs|hr|careers|jobs|procurement|purchasing|"
                          r"finance|accounts|management|webmaster|service|services|booking|reservations?)[\w.-]*@",
                          re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _clean(value) -> str:
    return " ".join(str(value if value is not None else "").split()).strip(" ,;:|")


def header_map(header: list[str], columns: dict | None = None) -> dict[str, int]:
    patterns = {k: re.compile(v, re.IGNORECASE) for k, v in (columns or DEFAULT_COLUMNS).items()}
    mapping: dict[str, int] = {}
    for name, rx in patterns.items():
        idx = next((i for i, h in enumerate(header) if h and rx.search(h.strip()) and i not in mapping.values()), None)
        if idx is not None:
            mapping[name] = idx
    return mapping


def rows_records(rows: list[list], *, columns: dict | None = None, default_company: str | None = None,
                 event: dict | None = None, excerpt_prefix: str = "") -> list[Record]:
    """Records of a table: the first row (within the first 10) that maps a company or a person column is the
    header. A row without a company is kept only when the whole source is one company's (default_company)."""
    rows = [[_clean(c) for c in r] for r in rows if any(_clean(c) for c in r)]
    for start, header in enumerate(rows[:10]):
        mapping = header_map(header, columns)
        if ("company" in mapping or default_company) and "person" in mapping or "company" in mapping and len(
                mapping) >= 3:
            break
    else:
        return []
    records: list[Record] = []
    for row in rows[start + 1:]:
        entry = {f: row[i] for f, i in mapping.items() if i < len(row) and row[i]}
        if entry.get("last_name") and entry.get("person"):
            entry["person"] = f"{entry['person']} {entry.pop('last_name')}"
        records += entry_records(entry, default_company=default_company, event=event,
                                 excerpt=(excerpt_prefix + " | ".join(c for c in row if c))[:500])
    return records


def _domains_of(website: str | None) -> list[str]:
    """'www.omega.example' / 'https://omega.example/en' -> ['omega.example']."""
    if not website:
        return []
    from app.services.people.external.lebanon.parsers import _domains

    return _domains(website) or _domains(f"https://{_clean(website)}")


def entry_records(entry: dict, *, default_company: str | None = None, event: dict | None = None,
                  excerpt: str = "", page: int | None = None) -> list[Record]:
    """An organisation record (company facts / event participation) and, when the entry names a person with a title,
    the person's record with the contact points that are the person's."""
    company = _clean(entry.get("company") or default_company or "")
    if len(company) < 2:
        return []
    emails = _EMAIL.findall(entry.get("email") or "")
    personal = next((e.lower() for e in emails if not ROLE_MAILBOX.match(e)), None)
    mailbox = next((e.lower() for e in emails if ROLE_MAILBOX.match(e)), None)
    domains = _domains_of(entry.get("website"))
    facts: dict = {}
    if mailbox:
        facts["email"] = mailbox
    for key in ("sector", "city", "booth"):
        if entry.get(key):
            facts[key] = _clean(entry[key])
    year = (event or {}).get("year")
    if event:
        facts["event"] = dict(event)
    person, title = _clean(entry.get("person")), _clean(entry.get("title"))
    if entry.get("department") and title and _clean(entry["department"]).lower() not in title.lower():
        title = f"{title}, {_clean(entry['department'])}"
    phone, mobile, whatsapp = (_clean(entry.get(k)) or None for k in ("phone", "mobile", "whatsapp"))
    if not (person and title) and phone:
        facts["phone"] = phone  # an organisation's number (no named person to own it)
    base = dict(org=[company], domains=domains, page=page, published=f"{year}-12-31" if year else None)
    out = [Record(**base, excerpt=excerpt, facts=facts)]
    if person and title:  # explicit name + title + company only
        contact = {"whatsapp": whatsapp} if whatsapp else {}
        out.append(Record(**base, person=person, title=title, excerpt=excerpt, email=personal,
                          phone=mobile or phone or whatsapp, facts=contact))
    return out


# ---- formats ------------------------------------------------------------------------------------------------------


def csv_rows(text: str) -> list[list[str]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def xlsx_rows(raw: bytes) -> list[list]:
    """Every sheet's rows, one after another (a header row starts each sheet's table)."""
    if raw[:2] == b"PK":
        from openpyxl import load_workbook

        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        return [list(r) for sheet in book.worksheets for r in sheet.iter_rows(values_only=True)]
    import xlrd

    book = xlrd.open_workbook(file_contents=raw)
    return [sheet.row_values(i) for sheet in book.sheets() for i in range(sheet.nrows)]


def html_table_rows(html: str) -> list[list[list[str]]]:
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(html or "<html/>")
    return [[[_clean(c.text_content()) for c in tr if c.tag in ("td", "th")] for tr in table.iter("tr")]
            for table in tree.iter("table")]


def docx_text(raw: bytes) -> str:
    """The paragraphs and table cells of a Word document (stdlib: a .docx is a zip of XML)."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>|</w:tc>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def vcard_records(text: str, *, default_company: str | None = None) -> list[Record]:
    """Business cards (vCard 2.1 / 3.0 / 4.0): FN / N, TITLE / ROLE, ORG, EMAIL, TEL (CELL = mobile), X-WHATSAPP."""
    text = re.sub(r"\r?\n[ \t]", "", text)  # unfolded lines
    records: list[Record] = []
    for card in re.findall(r"BEGIN:VCARD(.*?)END:VCARD", text, re.IGNORECASE | re.DOTALL):
        fields: dict[str, list[tuple[str, str]]] = {}
        for line in card.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            name, *params = key.split(";")
            fields.setdefault(name.split(".")[-1].upper(), []).append((";".join(params).upper(), value.strip()))
        first = lambda k: (fields.get(k) or [("", "")])[0][1]  # noqa: E731
        name = first("FN") or " ".join(reversed([p for p in first("N").split(";")[:2] if p]))
        org = first("ORG").split(";")[0] or default_company
        tels = fields.get("TEL") or []
        mobile = next((v for p, v in tels if "CELL" in p or "MOBILE" in p), None)
        work = next((v for p, v in tels if "CELL" not in p and "MOBILE" not in p and "HOME" not in p), None)
        whatsapp = first("X-WHATSAPP") or None
        email = next((v for p, v in fields.get("EMAIL") or [] if "HOME" not in p), None)
        entry = {"company": org, "person": name.replace("\\,", ","), "title": first("TITLE") or first("ROLE"),
                 "email": email, "mobile": mobile, "phone": work, "whatsapp": whatsapp, "website": first("URL")}
        records += entry_records(entry, excerpt=f"vCard: {name} {first('TITLE')} {org}"[:500])
    return records
