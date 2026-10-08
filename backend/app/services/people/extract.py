"""Person candidates from a company's own website pages (the parsed pages Step 4 stored: never fetched again
here). Deterministic and conservative: a person is only read where a role is stated next to a name.

    structured data   Person with worksFor = this company; Organization.founder / employee
    inline           "John Haddad – Chief Executive Officer", "CEO: John Haddad", "جوزيف حداد، المدير العام"
    cards            a name block followed (or preceded) by a title block on team / about / contact pages
    sentences        "our CEO, John Haddad", "led by Managing Director Michel Daher",
                     "Sarah Khoury was appointed as our new Marketing Director",
                     "the IT department is headed by Rami Saad",
                     former: "John Haddad served as CFO from 2018 to 2023", "former CEO John Haddad"

Never: testimonials / client quotes, article authors, people "at" another organisation, generic mailboxes, or
any name without a role. Emails / phones only when published in the person's own entry (Step 6 infers).
"""

import re
from collections import Counter
from dataclasses import replace
from datetime import date, datetime

from app.services.discovery.consolidation import name_tokens as company_tokens
from app.services.enrichment.extract import _EMAIL, _NUMBER, _ROLE_PURPOSE, Context, _phone, _related, _str, _types, \
    _walk
from app.services.enrichment.pages import Doc
from app.services.people.candidate import SOURCE_QUALITY, PersonCandidate
from app.services.people.names import clean_name, is_person_name, is_placeholder, split_name
from app.services.people.titles import Title, classify, fold, is_department

_SKIP_SECTION = re.compile(r"testimonial|what (our )?(clients|customers|guests|partners) say|reviews|témoignages|"
                           r"client stories|آراء|شهادات", re.IGNORECASE)
_NOT_PERSON_LINE = re.compile(r"^(by|posted by|written by|author|photo( by)?|credit|source|published|©)\b",
                              re.IGNORECASE)
_QUOTE = re.compile(r'^\s*[“"«„]')
_SEPARATOR = re.compile(r"\s+[–—-]\s+|\s*\|\s*|\s*[،,]\s+|\s*:\s+|\s+/\s+")
_EXTERNAL = re.compile(r"\b(?:at|of|chez|with|from)\s+((?:[A-Z][\w&.'’-]*\s*){1,5})")
_FORMER = re.compile(r"\b(former|formerly|ex-|previously|retired|stepped down|served as|until \d{4}|ancien|"
                     r"ancienne|سابق|سابقا)\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(19[5-9]\d|20\d{2})\b")
_LAST_N = 6  # words considered on each side of a trigger
_TITLE_END = {"from", "since", "in", "at", "until", "between", "for", "to", "who", "where", "with", "when", "on", "by",
              "and", "depuis", "chez", "منذ"}
_FILLER = {"our", "the", "its", "your", "their"}
_LEAD_VERBS = {"appointed", "named", "elected", "became", "becomes", "new", "acting", "interim"}
_TITLE_GLUE = {"of", "and", "&", "de", "du", "des", "la", "le", "d", "l", "et", "for", "in", "en", "-", "–", "—", "/"}
# Name / title cards and "Name – Title" lines are only read where a company lists its people.
_PEOPLE_PAGES = ("team", "about", "contact", "careers", "news")


def _strong(title: Title | None) -> Title | None:
    """For name/title layouts: a known title or a seniority word (manager, director, head...); a bare role word
    ('Skincare Pro Advisor' on a shop page) is not enough to call a name a person."""
    return title if title and (title.explicit or title.seniority != "individual_contributor") else None


def _title_like(text: str) -> bool:
    """A title, not prose: 'Head of Commercial and Retail Banking Division' yes; 'peak the eco-friendly farm
    tended by Chief Gardener' no (more than one lower-case word that is not title glue)."""
    words = re.findall(r"[^\W\d_][\w'’-]*", text)
    if not words or not all(w.isascii() or not w.isalpha() for w in words if w[0].isalpha() and w.isalpha()):
        return True  # non-Latin script: no letter case to judge by
    return len(words) <= 10 and sum(w.islower() and w not in _TITLE_GLUE for w in words) <= 1


def _words_before(text: str, end: int) -> str:
    return " ".join(text[:end].split()[-_LAST_N:])


def _words_after(text: str, start: int) -> str:
    return " ".join(re.split(r"[.;:()\n]", text[start:], maxsplit=1)[0].split()[:10])


def _title_part(text: str) -> str:
    """'our former Marketing Director, retired in 2021' -> 'Marketing Director'."""
    words = text.split(",")[0].split()
    while words and words[0].lower() in _FILLER | _LEAD_VERBS | {"former", "ex", "ancien", "ancienne"}:
        words = words[1:]
    cut = next((i for i, w in enumerate(words) if i and w.lower() in _TITLE_END), len(words))
    return " ".join(words[:cut])


def _person_contacts(item: dict) -> str:
    """A schema.org Person's own email / telephone (and its contactPoint's), as text for the contact reader."""
    points = item.get("contactPoint")
    points = points if isinstance(points, list) else [points] if isinstance(points, dict) else []
    values = [item.get("email"), item.get("telephone")] + [p.get(k) for p in points for k in ("email", "telephone")]
    return " ".join(str(v).removeprefix("mailto:").removeprefix("tel:") for v in values if isinstance(v, str))


def _org_credit(name: str, rest: str) -> bool:
    """'Head of IT & PMO, ABC Mall, Lebanon' / 'IT Director, BDO ESNAD, Egypt': a testimonial credit (title,
    organisation, country), not a person; a person's name is not followed by (or ending in) a country or city."""
    from app.services.query_understanding import COUNTRY_WORDS

    after = re.split(r"[,;()]|\s[–—-]\s", rest.strip(" ,;–—-"), maxsplit=1)[0].strip().lower()
    return name.split()[-1].lower() in COUNTRY_WORDS or after in COUNTRY_WORDS


def _year(text: str) -> int | None:
    years = [int(y) for y in _YEAR.findall(text) if int(y) <= date.today().year]
    return max(years) if years else None


class _Page:
    def __init__(self, doc: Doc, page_type: str, ctx: Context, source_id: int, url: str | None,
                 observed_at: datetime, ownership: int | None):
        self.doc, self.page_type, self.ctx = doc, page_type, ctx
        self.source_id, self.url, self.observed_at = source_id, url, observed_at
        self.exclude = {fold(t) for t in company_tokens(ctx.company_name)}
        factor = 1.0 if (ownership or 0) >= 60 else 0.9
        self.quality = SOURCE_QUALITY.get(page_type, SOURCE_QUALITY["other"])
        self.match = round(self.quality * factor)
        self.found: dict[tuple, PersonCandidate] = {}

    # ---- building a candidate ----------------------------------------------------------------------------

    def add(self, name: str, title: Title, excerpt: str, *, status: str = "current", started: int | None = None,
            ended: int | None = None, contact_text: str = "", biography: str | None = None,
            profile_url: str | None = None, source_type: str | None = None) -> None:
        name = clean_name(name)
        if not is_person_name(name, self.exclude) or is_placeholder(excerpt):
            return  # (a theme's demo bio is not evidence of anything)
        if self.page_type == "news" and status == "current":
            year = started or _year(excerpt)
            if year and year < date.today().year - 1:
                status = "unknown"  # an old announcement is history, not proof of a current role
        first, middle, last = split_name(name)
        candidate = PersonCandidate(
            source_id=self.source_id, source_url=self.url, source_type=source_type or self.page_type,
            company_id=0, full_name=name, raw_title=title.raw[:300], evidence_excerpt=excerpt.strip()[:600],
            observed_at=self.observed_at, first_name=first, middle_name=middle, last_name=last,
            normalized_title=title.normalized, department=title.department, seniority=title.seniority,
            title_rank=title.rank, title_explicit=title.explicit, status=status,
            started_at=date(started, 1, 1) if started else None, ended_at=date(ended, 1, 1) if ended else None,
            biography=biography, profile_url=profile_url, source_confidence=self.quality,
            company_match_confidence=self.match,
            # what the statement was read from: external sources must name the company in it
            raw_metadata={"page_type": self.page_type, "context": f"{excerpt} {contact_text}"[:1500]})
        self._contacts(candidate, contact_text)
        key = (fold(name), fold(title.normalized or title.raw))
        if key not in self.found or (self.found[key].status != "current" and status == "current"):
            self.found[key] = candidate

    def _contacts(self, c: PersonCandidate, text: str) -> None:
        """A business email / phone published in the person's own entry (never a generic mailbox)."""
        tokens = {t for t in fold(c.full_name).split() if len(t) >= 3}
        for m in _EMAIL.finditer(text):
            local = m[0].split("@")[0].lower()
            if re.sub(r"[^a-z]", "", local) not in _ROLE_PURPOSE and (
                    not tokens or any(t in fold(local.replace(".", " ")) or t in local for t in tokens)):
                c.email = m[0].lower()
                break
        for m in _NUMBER.finditer(text):
            if number := _phone(m[0], self.ctx):
                c.phone = number
                break

    def external(self, after: str) -> bool:
        """'CEO of XYZ Holding': a role at another organisation (not this company's employee). 'Head of IT' /
        'Director of Marketing' name a department, not an organisation."""
        for m in _EXTERNAL.finditer(after[:80]):
            org = m[1].strip()
            if not _related(org, self.ctx) and not is_department(org):
                return True
        return False

    # ---- sources on the page ---------------------------------------------------------------------------------

    def structured(self) -> None:
        for item in _walk(self.doc.jsonld):
            kinds = _types(item)
            if "Person" in kinds:
                employer = item.get("worksFor") or item.get("affiliation")
                employer_name = _str(employer) if employer else None
                if employer_name and _related(employer_name, self.ctx) and (title := classify(_str(item.get(
                        "jobTitle")))):
                    url = _str(item.get("url")) or _str(item.get("sameAs"))
                    self.add(_str(item.get("name")) or "", title, f"structured data: {item.get('name')}, "
                             f"{item.get('jobTitle')} at {employer_name}", profile_url=url,
                             source_type="structured_data", contact_text=_person_contacts(item))
            elif kinds and _related(_str(item.get("name")), self.ctx):
                for key, default in (("founder", "Founder"), ("employee", None), ("employees", None)):
                    people = item.get(key)
                    for person in (people if isinstance(people, list) else [people]):
                        if isinstance(person, dict) and (title := classify(_str(person.get("jobTitle")) or default)):
                            self.add(_str(person.get("name")) or "", title,
                                     f"structured data: {key} {person.get('name')}", source_type="structured_data",
                                     contact_text=_person_contacts(person))

    def _cards(self, rows: list[tuple[str, str]]) -> dict[int, tuple[str, str, int]]:
        """Team-page cards: a page lists people either name-then-title or title-then-name. The layout is read
        from the whole page (the more frequent adjacent order; a tie goes to whichever comes first), then each
        block is paired at most once, so a name never takes its neighbour's title."""
        if self.page_type not in _PEOPLE_PAGES:
            return {}
        kinds = []
        for _, text in rows:
            if len(text) <= 60 and is_person_name(text, self.exclude):
                kinds.append("N")
            elif len(text) <= 100 and _title_like(_title_part(text)) and _strong(classify(_title_part(text))):
                kinds.append("T")
            else:
                kinds.append("-")
        # Cards repeat the same markup (names in <h3>, titles in <h4>...): only pairs with the page's dominant
        # (name tag, title tag) decide, so a menu item that looks like a name cannot tip the layout.
        pairs = [(i, (kinds[i], kinds[i + 1])) for i in range(len(kinds) - 1)
                 if (kinds[i], kinds[i + 1]) in (("N", "T"), ("T", "N"))]
        tags = Counter((rows[i][0], rows[i + 1][0]) if order == ("N", "T") else (rows[i + 1][0], rows[i][0])
                       for i, order in pairs)
        if not tags:
            return {}
        dominant = tags.most_common(1)[0][0]
        pairs = [(i, order) for i, order in pairs if ((rows[i][0], rows[i + 1][0]) if order == ("N", "T")
                                                       else (rows[i + 1][0], rows[i][0])) == dominant]
        nt = sum(order == ("N", "T") for _, order in pairs)
        tn = len(pairs) - nt
        order = ("N", "T") if nt > tn else ("T", "N") if tn > nt else pairs[0][1]
        if nt == tn:
            # a tie: one card's name was not read as a name ("H.E. Mr. X"), leaving its title unpaired. That card
            # still has the name tag: just before the first title (name-then-title) or just after the last one
            # (title-then-name). Without this, every name would take the previous card's title.
            name_tag, title_tag = dominant
            titles = [i for i, k in enumerate(kinds) if k == "T" and rows[i][0] == title_tag]
            before = titles[0] > 0 and rows[titles[0] - 1][0] == name_tag and kinds[titles[0] - 1] != "N"
            after = titles[-1] + 1 < len(rows) and rows[titles[-1] + 1][0] == name_tag \
                and kinds[titles[-1] + 1] != "N"
            if before != after:
                order = ("N", "T") if before else ("T", "N")
        cards, i = {}, 0
        while i < len(kinds) - 1:
            if (kinds[i], kinds[i + 1]) == order:
                name_i, title_i = (i, i + 1) if order == ("N", "T") else (i + 1, i)
                cards[i] = (rows[name_i][1], rows[title_i][1], name_i)
                i += 2
            else:
                i += 1
        return cards

    def blocks(self) -> None:
        rows = [(tag, text) for tag, text, area in self.doc.blocks if area != "nav"]
        cards = self._cards(rows)
        skipping, skip_level, skip_next = False, 9, 0
        for i, (tag, text) in enumerate(rows):
            if tag[0] == "h" and len(tag) == 2:
                level = int(tag[1])
                if skipping and level <= skip_level:
                    skipping = False
                if _SKIP_SECTION.search(text):
                    skipping, skip_level = True, level
                    continue
            if skipping:
                continue
            if _QUOTE.match(text) and len(text.split()) >= 6:
                skip_next = 2  # a quotation: the next lines name its author (a client), not an employee
                continue
            if skip_next:
                skip_next -= 1
                continue
            if _NOT_PERSON_LINE.match(text):
                continue
            nearby = " ".join(t for _, t in rows[i:i + 4])
            if i in cards:
                self.card(rows, *cards[i])
            elif len(text) <= 160 and self.page_type in _PEOPLE_PAGES:
                self.inline(text, nearby)
            if len(text) >= 25:
                self.sentences(text)

    def inline(self, text: str, nearby: str) -> None:
        bare = _EMAIL.sub(" ", text)
        bare = re.sub(r"\b(e-?mail|tel|phone|mob(ile)?|t|m|e)\s*[.:]\s*", " ", bare, flags=re.IGNORECASE)
        bare = _NUMBER.sub(" ", bare).strip(" ,;:|-–—")
        parts = _SEPARATOR.split(bare, maxsplit=1)
        if len(parts) != 2:
            return
        a, b = (p.strip(" ,;:|-–—") for p in parts)
        if is_person_name(a, self.exclude) and _title_like(_title_part(b)) and (title := _strong(classify(_title_part(b)))) \
                and not self.external(b):
            self.add(a, title, text, status="former" if _FORMER.search(text) else "current", contact_text=text)
        elif is_person_name(b, self.exclude) and _title_like(_title_part(a)) and (title := _strong(classify(_title_part(a)))) \
                and not self.external(a):
            self.add(b, title, text, status="former" if _FORMER.search(text) else "current", contact_text=text)

    def card(self, rows: list[tuple[str, str]], name: str, title_text: str, name_i: int) -> None:
        """One team-page card: its name and title blocks, then (up to the next card) its bio and contacts."""
        if not (title := _strong(classify(_title_part(title_text)))) or self.external(title_text):
            return
        title = replace(title, raw=title_text[:300])  # the full published title is kept
        entry = [t for _, t in rows[name_i:name_i + 4] if t != title_text]
        entry = entry[:next((k for k, t in enumerate(entry[1:], 1) if is_person_name(t, self.exclude)), len(entry))]
        bio = next((t for t in entry[1:] if len(t) >= 80), None)
        self.add(name, title, f"{name} — {title_text}", contact_text=" ".join(entry[:3]),
                 status="former" if _FORMER.search(title_text) else "current", biography=bio[:600] if bio else None)

    # Sentence triggers: (pattern, which side the name is on, the status it implies, a fixed title)
    _TRIGGERS = [
        (re.compile(r"\b(?:our|its|the company'?s|the group'?s)\s+(?:new\s+)?", re.IGNORECASE), "title_name", None),
        (re.compile(r"\b(?:led|headed|managed|run|directed)\s+by\s+(?:our\s+|its\s+|the\s+)?", re.IGNORECASE),
         "title_name", None),
        (re.compile(r"\bfounded(?:\s+in\s+\d{4})?\s+by\s+", re.IGNORECASE), "name_only", "Founder"),
        (re.compile(r"\bformer\s+", re.IGNORECASE), "title_name", "former"),
    ]
    _NAME_VERB = re.compile(
        r"\s+(?:is|serves as|acts as|has been appointed(?: as)?|was appointed(?: as)?|has been named|was named|"
        r"joins(?: us)? as|joined(?: us)? as|has joined(?: us)? as|takes over as|was promoted to|has been promoted "
        r"to|served as|retired as|stepped down as)\s+(?:our|the|its|the company'?s)?\s*(?:new\s+)?", re.IGNORECASE)
    _APPOINT = re.compile(r"\b(?:appoint(?:s|ed|ment of)|welcomes?|announces?|announce that|introduc(?:es|ing))\s+",
                          re.IGNORECASE)
    _DEPT_HEAD = re.compile(r"\b(?:the\s+)?([A-Za-z&/ ]{2,30}?)\s+(?:department|team|division|unit)\s+is\s+"
                            r"(?:headed|led|managed|run)\s+by\s+", re.IGNORECASE)

    def _split_title_name(self, phrase: str) -> tuple[str, Title] | None:
        """'Managing Director Michel Daher' -> (Michel Daher, Managing Director). The shortest title that is
        followed by a name wins: 'CEO Andre Fadel and MediLife General Manager Nicole Bassim' -> Andre Fadel, CEO."""
        words = phrase.replace(",", " ").split()
        while words and words[0].lower() in _FILLER | _LEAD_VERBS | {"and", "&", "et"}:
            words = words[1:]
        for k in range(1, len(words)):
            for size in (2, 3, 4):
                name = " ".join(words[k:k + size])
                title_text = " ".join(words[:k])
                if _title_like(title_text) and (title := classify(title_text)) and is_person_name(name, self.exclude):
                    return name, title
        return None

    def _leading_name(self, phrase: str) -> str | None:
        words = phrase.replace(",", " ").split()
        for size in (4, 3, 2):
            if is_person_name(" ".join(words[:size]), self.exclude):
                return " ".join(words[:size])
        return None

    def _trailing_name(self, phrase: str) -> str | None:
        words = phrase.split()
        for size in (4, 3, 2):
            if len(words) >= size and is_person_name(" ".join(words[-size:]), self.exclude):
                return " ".join(words[-size:])
        return None

    def _title_at_start(self, phrase: str) -> Title | None:
        """The title a phrase starts with, as short as its meaning allows: 'CEO of Rival Industries' -> 'CEO'
        (so 'of Rival Industries' can be checked as another organisation); 'Head of IT' stays whole."""
        words = phrase.split(",")[0].split()
        while words and words[0].lower() in _LEAD_VERBS | {"and", "&", "et"}:  # "..., and CEO Rizk El Khoury"
            words = words[1:]
        cut = next((i for i, w in enumerate(words) if i and w.lower().strip(",.") in _TITLE_END), len(words))
        words = words[:cut]
        longest = next((t for size in range(min(6, len(words)), 0, -1)
                        if _title_like(" ".join(words[:size])) and (t := classify(" ".join(words[:size])))
                        and t.explicit), None)
        if longest is None:
            return None
        return next(t for size in range(1, len(words) + 1)
                    if (t := classify(" ".join(words[:size]))) and t.normalized == longest.normalized)

    def sentences(self, text: str) -> None:
        year = _year(text)
        former_years = re.search(r"\b(?:from|between)\s+(\d{4})\s+(?:to|and|until|-|–)\s+(\d{4})", text)
        for trigger, shape, extra in self._TRIGGERS:
            for m in trigger.finditer(text):
                after = _words_after(text, m.end())
                if shape == "name_only" and (name := self._leading_name(after)):
                    founded = _year(text)  # founded decades ago: a historical fact, not proof of a current role
                    self.add(name, classify(extra), text,
                             status="unknown" if founded and founded < date.today().year - 25 else "current")
                elif shape == "title_name" and (found := self._split_title_name(after)):
                    name, title = found
                    if not self.external(after.split(name, 1)[-1]):
                        status = "former" if extra == "former" else "current"
                        self.add(name, title, text, status=status, ended=year if status == "former" else None)
        for m in self._NAME_VERB.finditer(text):
            name = self._trailing_name(_words_before(text, m.start()))
            title = self._title_at_start(_words_after(text, m.end()))
            if name and title and not self.external(_words_after(text, m.end())[len(title.raw):]):
                verb = m[0].lower()
                if any(w in verb for w in ("served", "retired", "stepped")):
                    self.add(name, title, text, status="former",
                             started=int(former_years[1]) if former_years else None,
                             ended=int(former_years[2]) if former_years else year)
                else:
                    self.add(name, title, text, started=year if "appoint" in verb or "join" in verb else None)
        for m in self._APPOINT.finditer(text):
            after = _words_after(text, m.end())
            name = self._leading_name(after)
            rest = re.split(r"\bas\s+(?:our|the|its)?\s*(?:new\s+)?", after, maxsplit=1, flags=re.IGNORECASE)
            if name and len(rest) == 2 and (title := self._title_at_start(rest[1])) and not self.external(
                    rest[1][len(title.raw):]):
                self.add(name, title, text, started=year)
        for m in re.finditer(r",\s+", text):  # "... contact Rita Haddad, HR Officer." (known titles only)
            after = _words_after(text, m.end())
            if re.match(r"(?:and|&|or|et)\b", after, re.IGNORECASE):
                continue  # "Andre Fadel, and MediLife General Manager, Nicole Bassim": a new list item
            name = self._trailing_name(_words_before(text, m.start()))
            title = self._title_at_start(re.sub(r"^(?:our|the|its)\s+", "", after, flags=re.IGNORECASE))
            if name and title and not self.external(after.split(title.raw, 1)[-1]):
                status = "former" if re.match(r"\s*(?:our\s+|the\s+)?former\b", after, re.IGNORECASE) else "current"
                self.add(name, title, text, status=status, ended=_year(text) if status == "former" else None)
        for m in re.finditer(r",\s+", text):  # "... and MediLife General Manager, Nicole Bassim, ..."
            before = re.split(r"[,;]", _words_before(text, m.start()))[-1].split()  # since the previous comma
            while before and before[0].lower() in ("and", "&", "et", "or"):
                before = before[1:]
            title = next((t for size in range(min(6, len(before)), 0, -1)
                          if _title_like(phrase := " ".join(before[-size:])) and (t := classify(phrase))
                          and t.explicit and not is_person_name(phrase, self.exclude)), None)
            if title and (name := self._leading_name(_words_after(text, m.end()))) \
                    and not self.external(_words_after(text, m.end())[len(name):]) \
                    and not _org_credit(name, _words_after(text, m.end())[len(name):]):
                self.add(name, title, text, status="former" if _FORMER.search(title.raw) else "current")
        for m in self._DEPT_HEAD.finditer(text):
            dept = [w for w in m[1].strip().split() if w.lower() not in _FILLER][-2:]
            name = self._leading_name(_words_after(text, m.end()))
            title = classify(f"Head of {' '.join(dept)}")
            if name and title:
                self.add(name, title, text)


def extract(doc: Doc, page_type: str, *, ctx: Context, source_id: int, url: str | None, observed_at: datetime,
            ownership: int | None) -> list[PersonCandidate]:
    page = _Page(doc, page_type, ctx, source_id, url, observed_at, ownership)
    page.structured()
    page.blocks()
    return list(page.found.values())
