"""Person names: display clean-up, comparison keys, and "is this text a person's name?".

Display names keep their form (accents, Arabic script, hyphens, apostrophes); honorifics (Mr., Dr., Eng., السيد...)
are dropped. Comparison keys fold case / accents / Arabic letter variants, drop particles (el, al, abi, de...) and
map a short list of well-known forms of the same first name (Joe = Joseph = Youssef, Michel = Michael...). A
matching key is only one signal: resolution.py never merges on a name alone.
"""

import re

from app.services.discovery.geography import AREAS, _fold
from app.services.people.titles import is_title_word

HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "eng", "engr", "me", "m", "mme", "mlle", "prof", "sheikh", "sir",
              "madam", "madame", "monsieur", "he", "السيد", "السيدة", "الدكتور", "الدكتورة", "د", "م", "المهندس",
              "المهندسة", "الشيخ", "الاستاذ", "الأستاذ", "المحامي"}
PARTICLES = {"el", "al", "de", "du", "da", "del", "la", "le", "abi", "abou", "abu", "bou", "ben", "bin", "van", "von",
             "di", "d", "ibn"}
# Forms of one first name (keys only, never displayed). Deliberately short: Johnny is not John.
_FIRST_NAMES = {
    "joseph": ["joe", "jo", "youssef", "yousef", "yusuf", "joseph", "josef"],
    "michael": ["michel", "michael", "mike", "mikhael", "mikael", "michele"],
    "anthony": ["anthony", "antoine", "tony", "antonio", "antony"],
    "elias": ["elie", "elias", "eli", "elia", "ilyas"],
    "george": ["george", "georges", "gerges", "jirjis", "jorge"],
    "mohammad": ["mohammad", "mohamad", "mohammed", "mohamed", "muhammad", "muhammed", "mhamad"],
    "ahmad": ["ahmad", "ahmed"],
    "hussein": ["hussein", "hussain", "husayn", "hussien"],
    "peter": ["peter", "pierre", "boutros", "pietro"],
    "nicholas": ["nicholas", "nicolas", "nicola", "nicolai"],
    "philip": ["philip", "philippe", "phillip"],
    "mark": ["mark", "marc"],
    "charbel": ["charbel", "sharbel"],
    "ibrahim": ["ibrahim", "abraham"],
    "alexander": ["alexander", "alexandre", "alex"],
    "christopher": ["christopher", "chris"],
}
FIRST_NAME = {form: canonical for canonical, forms in _FIRST_NAMES.items() for form in forms}
_SURNAMES = {"khouri": "khoury", "hadad": "haddad", "nasr": "nasr", "nassar": "nassar"}

# Words that never make a person's name (beyond title words and the company's own name).
_NOT_NAME = set("""team our the company department office group holding sal sarl ltd inc llc co contact us about home
services service products product news careers career read more view profile board management leadership members
member directors staff welcome lebanon liban beirut beyrouth middle east arab lebanese international national
general all rights reserved copyright privacy policy terms phone email tel fax mobile address location map
january february march april may june july august september october november december monday tuesday wednesday
thursday friday saturday sunday new our your their this that with from and for department division unit
banking bank banks corporate retail private personal business investment investments wealth asset assets insurance
financial finance services solutions group holdings holding network branches branch markets market capital fund
funds trade trading treasury credit loans loan cards card account accounts deposit deposits savings mortgage leasing
industrial industries industry products product quality global regional local digital online mobile internet
customer customers client clients community social corporate governance compliance risk sustainability careers
investor investors relations media centre center fresh time current welcome history mission vision values awards
annual report reports division divisions sector sectors sme smes consumer commercial university universite
university college school ecole hospital hopital clinic association foundation fondation institute institut church eglise
ministry municipality syndicate order council committee club federation chamber
northern southern eastern western border region regions area zone americas europe asia pacific africa""".split())
_LATIN = re.compile(r"^(?:[A-ZÀ-ÖØ-Þ][a-zß-öø-ÿ'’\-]+(?:-[A-ZÀ-ÖØ-Þ][a-zß-öø-ÿ'’]+)?|[A-ZÀ-ÖØ-Þ]{2,}|[A-Z]\.)$")
_ARABIC = re.compile(r"^[ء-ي٠-٩]{2,}$")
_AR_NOT_NAME = {"مدير", "مديرة", "رئيس", "رئيسة", "قسم", "شركة", "فريق", "الادارة", "الإدارة", "مجلس", "العام",
                "التنفيذي", "المالي", "التسويق", "المبيعات", "المؤسس", "مؤسس", "نائب", "مسؤول", "مسؤولة", "لبنان",
                "بيروت", "عن", "اتصل", "بنا", "خدمة", "العملاء", "الموارد", "البشرية", "تكنولوجيا", "المعلومات"}


def _places() -> set[str]:
    return {_fold(n) for areas in AREAS.values() for a in areas.values() for n in (a.label, *a.names)}


_PLACES = _places()


def clean_name(raw: str) -> str:
    """'Dr. JOHN  HADDAD,' -> 'John Haddad'; Arabic kept as is."""
    tokens = [t for t in re.split(r"\s+", raw.strip(" ,;:-–—|.()")) if t]
    while tokens and _fold(tokens[0]).strip() in HONORIFICS:
        tokens = tokens[1:]
    tokens = [t.capitalize() if t.isupper() and len(t) > 2 and not _ARABIC.match(t) else t for t in tokens]
    return " ".join(tokens)


def name_tokens(name: str) -> list[str]:
    return [t for t in _fold(clean_name(name)).split() if t not in HONORIFICS]


def name_key(name: str) -> tuple[str, ...]:
    """Comparison key: folded tokens without particles; the first name in its canonical form."""
    tokens = [t for t in name_tokens(name) if t not in PARTICLES]
    if not tokens:
        return ()
    tokens[0] = FIRST_NAME.get(tokens[0], tokens[0])
    tokens[-1] = _SURNAMES.get(tokens[-1], tokens[-1])
    return tuple(tokens)


def split_name(name: str) -> tuple[str | None, str | None, str | None]:
    """(first, middle, last) of a display name; particles stay with the last name ('Rami El Khoury')."""
    tokens = clean_name(name).split()
    if len(tokens) < 2:
        return (tokens[0] if tokens else None), None, None
    last_start = len(tokens) - 1
    while last_start > 1 and _fold(tokens[last_start - 1]) in PARTICLES:
        last_start -= 1
    middle = " ".join(tokens[1:last_start]) or None
    return tokens[0], middle, " ".join(tokens[last_start:])


# Website-theme demo content and placeholders: never people, never evidence (any source).
_PLACEHOLDER = re.compile(r"lorem ipsum|dolor sit amet|consectetur adipiscing|wordpress theme|theme reach new heights|"
                          r"demo (?:content|text|user)|sample (?:text|profile)|your name here|"
                          r"\b(?:john|jane|jhon) doe\b|"
                          r"\bteam member \d|\bfirstname lastname\b", re.IGNORECASE)


def is_placeholder(text: str | None) -> bool:
    return bool(text and _PLACEHOLDER.search(text))


def is_person_name(text: str, exclude: set[str] = frozenset()) -> bool:
    """A plausible personal name: 2-5 name-shaped words, none a title / organisation / place / common word.
    `exclude`: folded words of the company's own name."""
    name = clean_name(text)
    if not name or is_placeholder(name) or len(name) > 60 or any(ch.isdigit() for ch in name) or "@" in name:
        return False
    tokens = name.split()
    if not 2 <= len(tokens) <= 5:
        return False
    folded = [_fold(t) for t in tokens]
    if any(f in exclude or f in _NOT_NAME or f in _PLACES or is_title_word(t) for f, t in zip(folded, tokens)
           if f not in PARTICLES):
        return False
    if any(len(f.split()) > 1 and any(is_title_word(p) or p in _NOT_NAME for p in f.split()) for f in folded):
        return False  # "Vice-président Joe ...": a hyphenated title, not a compound first name
    if all(_ARABIC.match(t) for t in tokens):
        return not set(tokens) & _AR_NOT_NAME and not any(t.startswith("ال") and t[2:] in _AR_NOT_NAME for t in tokens)
    words = [t for t, f in zip(tokens, folded) if f not in PARTICLES]
    if not all(_LATIN.match(t) for t in words):
        return False
    proper = [t for t in words if not t.endswith(".")]
    return len(proper) >= 2 or (len(proper) == 1 and len(words) >= 2 and len(proper[0]) >= 3)
