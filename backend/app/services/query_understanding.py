"""Query understanding for direct company search (Step 5.4.1): what the user typed -> a structured search intent.

Deterministic (no AI, no company names in code): a company is never invented here, only the user's words are sorted.

    'find me Formatech'                                  -> name 'Formatech'
    'Lebanese training company Formatech'                -> name 'Formatech', country Lebanon, industry Training
    'hotel called Aleph in Byblos'                       -> name 'Aleph', city Byblos, industry Hospitality
    'I think the company is called ABC and they
     distribute food in Lebanon'                         -> name 'ABC', country Lebanon, industry Distribution
    'technology company called X in Dubai'               -> name 'X', city Dubai, country United Arab Emirates
    'شركة صناعية في بيروت اسمها الأرز'                   -> name 'الأرز', city Beirut, industry Manufacturing
    'www.example.com' / 'https://example.com/en'         -> domain example.com
    'ABC Foods SAL'                                      -> name 'ABC Foods SAL' (legal form hint SAL)

The name keeps the user's spelling (matching normalizes it later). Without a marker ('called', 'named', 'اسمها'),
context words (a known industry word, 'in <place>', a country adjective, filler like 'find me') are peeled off the
ends; whatever remains is the name. A query that is only context ('hotels in Beirut') has no name.
"""

import re
from dataclasses import asdict, dataclass, field

from app.services.discovery.geography import AREAS, _fold, find_country
from app.services.normalization import company_domain

_ARABIC = re.compile(r"[؀-ۿ]")
_DOMAIN = re.compile(r"^(https?://)?(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", re.IGNORECASE)

# industry words -> the industry label LeadFinder uses (English, French, Arabic; singular and plural)
INDUSTRY_WORDS: dict[str, str] = {}
for label, words in {
    "Hospitality": "hotel hotels resort resorts motel hostel guesthouse hôtel فندق فنادق منتجع",
    "Restaurants": "restaurant restaurants cafe café coffee shop bakery bistro pub bar مطعم مطاعم مقهى",
    "Training": "training trainings formation coaching تدريب",
    "Education": "school schools university college academy institute nursery مدرسة مدرسه جامعة جامعه معهد",
    "Technology": "technology tech software it startup startups saas digital ict تكنولوجيا برمجيات",
    "Manufacturing": "manufacturer manufacturers manufacturing factory factories industrial industry industries "
                     "plant usine صناعية صناعيه مصنع معمل صناعة",
    "Food Manufacturing": "food foods",
    "Distribution": "distributor distributors distribution wholesale wholesaler importer importers trading "
                    "distribute distributes توزيع موزع تجارة",
    "Logistics": "logistics shipping freight transport forwarding شحن",
    "Construction": "construction contractor contractors contracting builder engineering مقاولات مقاول بناء",
    "Real Estate": "real-estate realestate property properties developer عقارات",
    "Professional Services": "consulting consultancy consultants audit accounting law lawyers firm استشارات",
    "Marketing": "marketing advertising agency agencies branding إعلان",
    "Travel": "travel tourism tours سياحة سفر",
    "Pharmaceutical": "pharma pharmaceutical pharmaceuticals pharmacy drugstore صيدلية أدوية",
    "Healthcare": "hospital hospitals clinic clinics medical healthcare مستشفى مستشفيات عيادة",
    "Retail": "retail store stores shop shops boutique supermarket متجر محل",
    "Financial Services": "bank banks banking finance financial مصرف بنك",
    "Insurance": "insurance insurer assurance تأمين تامين",
    "Telecom": "telecom telecommunications isp internet اتصالات",
}.items():
    for word in words.split():
        INDUSTRY_WORDS[_fold(word)] = label

# countries and cities a query may name (context only: discovery itself is configured per country)
COUNTRY_WORDS = {"lebanon": "Lebanon", "lebanese": "Lebanon", "liban": "Lebanon", "libanais": "Lebanon",
                 "libanaise": "Lebanon", "لبنان": "Lebanon", "لبنانية": "Lebanon", "لبنانيه": "Lebanon",
                 "uae": "United Arab Emirates", "emirates": "United Arab Emirates", "dubai": "United Arab Emirates",
                 "abu dhabi": "United Arab Emirates", "saudi": "Saudi Arabia", "ksa": "Saudi Arabia",
                 "riyadh": "Saudi Arabia", "jeddah": "Saudi Arabia", "qatar": "Qatar", "doha": "Qatar",
                 "kuwait": "Kuwait", "jordan": "Jordan", "amman": "Jordan", "egypt": "Egypt", "cairo": "Egypt",
                 "iraq": "Iraq", "erbil": "Iraq", "baghdad": "Iraq", "cyprus": "Cyprus", "france": "France",
                 "paris": "France", "syria": "Syria", "oman": "Oman", "bahrain": "Bahrain"}
FOREIGN_CITIES = {"dubai": "Dubai", "abu dhabi": "Abu Dhabi", "riyadh": "Riyadh", "jeddah": "Jeddah",
                  "doha": "Doha", "amman": "Amman", "cairo": "Cairo", "erbil": "Erbil", "baghdad": "Baghdad",
                  "paris": "Paris"}
COUNTRY_TLD = {"Lebanon": "lb", "United Arab Emirates": "ae", "Saudi Arabia": "sa", "Qatar": "qa", "Kuwait": "kw",
               "Jordan": "jo", "Egypt": "eg", "Iraq": "iq", "Cyprus": "cy", "France": "fr", "Oman": "om",
               "Bahrain": "bh"}
_FILLER = {"find", "me", "search", "for", "look", "looking", "the", "a", "an", "company", "companies", "firm",
           "business", "brand", "group", "i", "think", "it", "is", "its", "it's", "called", "named", "name",
           "and", "they", "that", "which", "who", "in", "at", "from", "based", "of", "please", "show", "get",
           "open", "société", "societe", "entreprise", "شركة", "شركه", "مؤسسة", "مؤسسه", "في", "اسمها", "اسمه",
           "تدعى", "يدعى", "ابحث", "عن"}
# markers after which the name follows ('called X', 'named X', 'اسمها X')
_MARKERS = re.compile(r"\b(?:called|named|name is|known as|نام|appelée?|nommée?|dite?)\s+|(?:اسمها|اسمه|تدعى|يدعى)\s+",
                      re.IGNORECASE)
_LEGAL_FORM = re.compile(r"\b(s\.?\s?a\.?\s?l|s\.?\s?a\.?\s?r\.?\s?l|holding|offshore|ltd|llc|inc|co|corp)\.?$",
                         re.IGNORECASE)


@dataclass
class Intent:
    raw: str
    name: str | None = None  # the company name as the user wrote it
    core_name: str | None = None  # the name without leading / trailing industry or place words
    domain: str | None = None
    country: str | None = None
    city: str | None = None
    region: str | None = None
    industry: str | None = None
    language: str = "en"
    legal_form: str | None = None
    context_words: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], "")}


def _place(words: list[str]) -> tuple[str | None, str | None, str | None]:
    """(city, region, country) named by these words (one or two words: 'abu dhabi')."""
    text = " ".join(words)
    folded = _fold(text)
    for area in AREAS.get("LB", {}).values():
        if folded in area.keys or folded == _fold(area.label):
            return (area.label if area.kind == "city" else None,
                    area.region if area.kind == "city" else area.label, "Lebanon")
    if folded in FOREIGN_CITIES:
        return FOREIGN_CITIES[folded], None, COUNTRY_WORDS.get(folded)
    if folded in COUNTRY_WORDS:
        return None, None, COUNTRY_WORDS[folded]
    if (country := find_country(text)) is not None:
        return None, None, country.name
    return None, None, None


_CONNECTORS = {"of", "de", "du", "des", "d", "la", "le", "les", "al", "el", "and", "et", "the", "&", "for", "pour"}
_GENERIC_SINGLE = {"banque", "bank", "societe", "company", "group", "groupe", "holding", "international", "general",
                   "national", "american", "arab", "united", "first", "new", "modern"}


def _is_context(word: str) -> bool:
    return word in _FILLER or word in INDUSTRY_WORDS or word in COUNTRY_WORDS


def _bare(word: str) -> str:
    return _fold(word.removesuffix("-based"))


def parse(raw: str, *, country: str | None = None) -> Intent:
    """The user's query as a search intent. `country` is the page's context (Find Leads' country), used only when
    the query names none."""
    raw = " ".join((raw or "").split())[:200]
    intent = Intent(raw=raw, language="ar" if _ARABIC.search(raw) else "en")
    if " " not in raw and _DOMAIN.match(raw) and (domain := company_domain(raw)):
        intent.domain, intent.country = domain, country
        return intent
    tokens = raw.strip(" .?!،").replace(",", " ").split()

    def note(word: str, first: bool = False) -> None:
        if (label := INDUSTRY_WORDS.get(_bare(word))) and not (first and intent.industry):
            intent.industry = label  # the last one is the head noun ('food distributor': Distribution)
            intent.context_words.append(word)

    def place(words: list[str], free_text: bool = False) -> bool:
        city, region, place_country = _place([_bare(w) for w in words])
        if not place_country and not free_text:
            return False
        intent.city = intent.city or city or (None if place_country else " ".join(words))
        intent.region = intent.region or region
        intent.country = intent.country or place_country
        return True

    # 1. a trailing clause about the company is context ('... and they distribute food in Lebanon')
    for i, t in enumerate(tokens):
        if i and _fold(t) in ("they", "which", "who", "where"):
            tail = tokens[i:]
            for k, w in enumerate(tail):
                note(w, first=True)  # 'they distribute food': the verb says what the company does
                if _fold(w) in ("in", "at", "في") and k + 1 < len(tail):
                    place(tail[k + 1:k + 3]) or place(tail[k + 1:k + 2])
            tokens = tokens[:i]
            if tokens and _fold(tokens[-1]) in ("and", "و"):
                tokens.pop()
            break
    # 2. a marker: the name follows it ('hotel called Aleph', 'company named X', 'شركة ... اسمها X')
    text = " ".join(tokens)
    marked = _MARKERS.search(text)
    if marked:
        before = text[:marked.start()].split()
        for k, w in enumerate(before):
            note(w)
            if _fold(w) in ("in", "at", "في") and k + 1 < len(before):
                place(before[k + 1:k + 2])
            else:
                place([w])
        tokens = text[marked.end():].split()
    # 3. 'in <place>' at the end: a known city / country, or a free-text place ('in Mar Mikhael', 'à Paris')
    for i in range(len(tokens) - 1, 0, -1):
        if _fold(tokens[i - 1]) in ("in", "at", "from", "في", "a", "au", "en") and i > 1 and (
                _fold(tokens[i - 1]) in ("in", "at", "from", "في") or _place([_bare(t) for t in tokens[i:]])[2]):
            place(tokens[i:], free_text=True)
            tokens = tokens[:i - 1]
            if tokens and _fold(tokens[-1]) == "based":
                tokens.pop()
            break
    if not marked:
        # '<descriptors> company <Name>' ('Lebanese training company Formatech'): the name follows 'company'
        for i, t in enumerate(tokens[:-1]):
            if _fold(t) in ("company", "firm", "business", "شركة", "شركه", "مؤسسة", "مؤسسه") and i and \
                    all(_is_context(_bare(w)) or _place([_bare(w)])[2] for w in tokens[:i]):
                for w in tokens[:i]:
                    note(w)
                    place([w])
                tokens = tokens[i + 1:]
                break
    # 4. filler at the start ('find me', 'search for')
    while len(tokens) > 1 and _fold(tokens[0]) in _FILLER - {"group"}:
        tokens.pop(0)
    while len(tokens) > 1 and _fold(tokens[-1]) in _FILLER - {"group", "co", "company"}:
        tokens.pop()
    if len(tokens) == 1 and _fold(tokens[0]) in _FILLER:
        tokens = []
    intent.name = " ".join(tokens).strip(" ,.-") or None
    # the core: the name without industry / place / country words at its ends ('Hotel Albergo' -> 'Albergo')
    core = list(tokens)
    while len(core) > 1 and (INDUSTRY_WORDS.get(_bare(core[0])) or _place([_bare(core[0])])[2]):
        note(core[0])
        place(core[:1])
        core.pop(0)
    while len(core) > 1 and (INDUSTRY_WORDS.get(_bare(core[-1])) or _place([_bare(core[-1])])[2]):
        note(core[-1])
        place(core[-1:])
        core.pop()
    while len(core) > 1 and _fold(core[0]) in _CONNECTORS:
        core.pop(0)
    while len(core) > 1 and _fold(core[-1]) in _CONNECTORS:
        core.pop()
    generic = len(core) == 1 and (_bare(core[0]) in INDUSTRY_WORDS or _fold(core[0]) in _FILLER | _CONNECTORS
                                  or _bare(core[0]) in _GENERIC_SINGLE or len(core[0]) < 3)
    intent.core_name = " ".join(core) if core != tokens and not generic else None
    if len(tokens) == 1 and INDUSTRY_WORDS.get(_bare(tokens[0])):
        note(tokens[0])
        intent.name = None  # 'hotels' alone (or 'hotels in Beirut'): no company name
    if intent.name and (legal := _LEGAL_FORM.search(intent.name)):
        intent.legal_form = legal.group(1).upper().replace(" ", "").replace(".", "")
    if not intent.country and country:
        intent.country = country
    return intent


def names(intent: Intent) -> list[str]:
    """The company names to search, most complete first: the full name, then its core."""
    return [n for n in dict.fromkeys((intent.name, intent.core_name)) if n]
