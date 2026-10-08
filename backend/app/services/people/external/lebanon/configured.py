"""A configured connector: one generic reader for simple public pages and documents (event speaker / exhibitor lists,
award programmes, association and chamber directories), driven by the source's `extract` settings in sources.json, so
a new source is configuration, not code.

    "extract": {
      "mode": "table" | "lines",
      # table: HTML tables; header cells mapped to fields by pattern (first matching header wins)
      "columns": {"company": "company|exhibitor|organi[sz]ation", "person": "name|speaker", "title": "title|position",
                  "phone": "phone|tel", "website": "web", "email": "mail", "sector": "sector|activity"},
      # lines: text lines of the HTML page or PDF; named groups person / title / company
      "line": "^(?P<person>...) [-–,] (?P<title>...) [-–,|] (?P<company>...)$",
      # lines with section context: a heading names the company for the people lines below it (until the next
      # heading, a page break or `section_lines` lines)
      "heading": "^(?P<company>[A-Z][A-Z0-9&'. -]{3,})$", "member": "^(?P<person>...) [-–:] (?P<title>...)$",
      "section_lines": 25,
      "event": {"name": "HORECA Lebanon", "year": 2026}   # optional: participation as a dated company event
    }
    "mode": "xpath": repeated items with relative fields; "page_company" names the company for the whole page
                     (a startup's profile page); "require" keeps only items whose field matches ({"country": "Lebanon"});
                     "technology": a technology the listing itself proves ("Odoo": an Odoo customer reference)
      {"item": "//div[contains(@class,'card-body')]", "fields": {"company": ".//h5", "sector": ".//a"}}
    "mode": "regex": named groups person + role over the raw page ("role" split into title / company at the last
                     " - ", ", ", " of ", " at ")
    "mode": "bios":  board pages: an upper-case name, the person's office at the association, then a biography;
                     company roles are read from the biography only (the office never becomes a company title)

People only with an explicit name + title + company (a speaker without employer, or a name without a title, is never
attached). Organisation-only entries still give company facts (phone, website, sector, event participation).
"""

import re

from app.services.people.external.lebanon.records import Record

FIELDS = ("company", "person", "title", "phone", "website", "email", "sector", "city", "description", "country")


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip(" ,;:-–|")


def _record(entry: dict, spec: dict, excerpt: str, page: int | None) -> list[Record]:
    company = _clean(entry.get("company", ""))
    if not company or len(company) < 2:
        return []
    facts: dict = {}
    for key in ("phone", "email", "city"):
        if entry.get(key):
            facts[key] = _clean(entry[key])
    if entry.get("sector"):
        facts["sector"] = _clean(entry["sector"])
    if spec.get("event"):
        facts["event"] = dict(spec["event"])
    if spec.get("technology"):
        facts["technology"] = spec["technology"]
    if entry.get("description") and len(_clean(entry["description"])) > 40:
        facts["description"] = _clean(entry["description"])[:1500]
    domains = []
    if entry.get("website"):
        from app.services.people.external.lebanon.parsers import _domains

        domains = _domains(entry["website"]) or _domains(f"https://{_clean(entry['website'])}")
    year = (spec.get("event") or {}).get("year")
    base = dict(org=[company], domains=domains, page=page, published=f"{year}-12-31" if year else None)
    out = [Record(**base, excerpt=excerpt[:500], facts=facts)]
    person, title = _clean(entry.get("person", "")), _clean(entry.get("title", ""))
    if person and title:  # explicit name + title + company only
        out.append(Record(**base, person=person, title=title, excerpt=excerpt[:500]))
    return out


def tables(html: str, spec: dict) -> list[Record]:
    """HTML tables: the header found automatically (generic.DEFAULT_COLUMNS) unless `columns` maps it."""
    from app.services.people.external import generic

    records: list[Record] = []
    for rows in generic.html_table_rows(html):
        records += generic.rows_records(rows, columns=spec.get("columns"), event=spec.get("event"),
                                        default_company=spec.get("page_company"))
    return records


def files(url: str, raw: bytes, spec: dict) -> list[Record] | None:
    """A spreadsheet / CSV / vCard / Word document of the source (None: not one of these: a PDF)."""
    from app.services.people.external import generic

    kind = url.lower().split("?")[0].rsplit(".", 1)[-1]
    common = dict(columns=spec.get("columns"), event=spec.get("event"), default_company=spec.get("page_company"))
    if kind in ("xlsx", "xls"):
        return generic.rows_records(generic.xlsx_rows(raw), **common)
    if kind == "csv":
        return generic.rows_records(generic.csv_rows(raw.decode("utf-8-sig", "replace")), **common)
    if kind == "vcf":
        return generic.vcard_records(raw.decode("utf-8", "replace"), default_company=spec.get("page_company"))
    if kind == "docx":
        return lines([(None, generic.docx_text(raw))], spec)
    return None


def lines(pages: list[tuple[int | None, str]], spec: dict) -> list[Record]:
    """pages: [(page number or None, text)]."""
    line_rx = re.compile(spec["line"]) if spec.get("line") else None
    heading_rx = re.compile(spec["heading"]) if spec.get("heading") else None
    member_rx = re.compile(spec["member"]) if spec.get("member") else None
    limit = int(spec.get("section_lines") or 25)
    records: list[Record] = []
    for page, text in pages:
        company, since = None, 0  # section context never crosses a page
        for raw in text.splitlines():
            line = _clean(raw)
            if not line:
                continue
            since += 1
            if line_rx and (m := line_rx.match(line)):
                records += _record(m.groupdict(), spec, line, page)
                continue
            if heading_rx and (m := heading_rx.match(line)):
                company, since = m.group("company"), 0
                records += _record({"company": company}, spec, line, page)
                continue
            if member_rx and company and since <= limit and (m := member_rx.match(line)):
                records += _record({**m.groupdict(), "company": company}, spec, f"{company}: {line}", page)[1:]
    return records


def _xtext(node, path: str) -> str:
    if not path:
        return ""
    found = node.xpath(path)
    if not found:
        return ""
    first = found[0]
    return _clean(first if isinstance(first, str) else first.text_content())


def xpath_items(html: str, spec: dict) -> list[Record]:
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(html or "<html/>")
    page_company = _xtext(tree, spec.get("page_company", ""))
    require = {k: re.compile(v, re.IGNORECASE) for k, v in (spec.get("require") or {}).items()}
    records: list[Record] = []
    for item in tree.xpath(spec["item"]):
        entry = {f: _xtext(item, p) for f, p in (spec.get("fields") or {}).items()}
        if page_company and not entry.get("company"):
            entry["company"] = page_company
        if any(not rx.search(entry.get(k, "")) for k, rx in require.items()):
            continue
        excerpt = " | ".join(v for v in (entry.get("company"), entry.get("person"), entry.get("title"),
                                          entry.get("sector")) if v)
        records += _record(entry, spec, excerpt, None)
    return _dedupe(records)


_SPLIT = (" - ", " – ", " — ", ", ", " of ", " at ", " @ ")


def regex_people(html: str, spec: dict) -> list[Record]:
    import html as html_lib

    records: list[Record] = []
    for m in re.finditer(spec["pattern"], html or ""):
        groups = {k: re.sub(r"\\u([0-9a-fA-F]{4})", lambda u: chr(int(u[1], 16)), html_lib.unescape(v or ""))
                  for k, v in m.groupdict().items()}  # JSON-escaped text in a page script ('\u0026')
        role = _clean(groups.pop("role", ""))
        title, company = groups.get("title", ""), groups.get("company", "")
        if role and not company:
            cut = max(((role.rfind(sep), sep) for sep in _SPLIT), key=lambda x: x[0])
            if cut[0] > 0:
                title, company = role[:cut[0]], role[cut[0] + len(cut[1]):]
        records += _record({"person": groups.get("person", ""), "title": title, "company": company}, spec,
                           f"{groups.get('person', '')} — {role}", None)
    return _dedupe(records)


def bios(doc, spec: dict) -> list[Record]:
    """Board / committee pages: NAME, office at the association, biography (company roles read from it later)."""
    name_rx = re.compile(spec.get("name") or r"^[A-Z][A-Z'. -]{4,40}$")
    texts = [t.strip() for _, t, area in doc.blocks if area not in ("nav", "footer") and t.strip()]
    records: list[Record] = []
    for i, text in enumerate(texts[:-2]):
        if not name_rx.match(text):
            continue
        office, bio = texts[i + 1], texts[i + 2]
        if len(office) > 60 or len(bio) < 60:
            continue
        records.append(Record(org=[], person=text.title(), association_role=office, bio=bio[:4000],
                              excerpt=f"{spec.get('association', 'Association')} board: {text.title()}, {office}"))
    return records


def _dedupe(records: list[Record]) -> list[Record]:
    seen, out = set(), []
    for r in records:
        key = (tuple(r.org), r.person, r.title)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out
