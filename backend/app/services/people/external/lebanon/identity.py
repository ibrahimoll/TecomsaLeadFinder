"""Multilingual company identity: how a public record is tied to a LeadFinder company, in stages of decreasing
strength. Deterministic (no AI); never merges companies; the canonical name is never rewritten.

    1 identifier        the same official number (registry, LEI, licence, bank list)                   97
    2 domain            the record's own website is the company's                                       92 (95 + name)
    3 name              the same name after legal forms / French-English word forms                     88
      core / acronym    the same distinctive part ('Arabia Insurance Co.' ~ 'Arabia Insurance')         80
    4 phone + name      the same published phone number and a shared name element                       85
    5 transliteration   an Arabic name whose consonant skeleton is the company's Latin name's ('مسابكي' ~
                        'Massabki') AND a second signal (same phone, or same town)                      75
    6 possible          a transliteration or a phone alone: recorded for diagnostics, never applied

A group / holding is never its subsidiary ('X Group' is not 'X'). Strong matches (stages 1-3) teach the company the
source's spelling as an alias (company_aliases), so its Arabic / French name then matches exactly elsewhere.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Company, CompanyAlias, CompanyIdentifier, Phone
from app.services.discovery.geography import _fold
from app.services.normalization import company_domain
from app.services.people.external.lebanon.records import (GROUP_WORDS, Record, _groupish, company_names, core_key,
                                                           keys_of, name_variants, org_key)

_ARABIC = re.compile(r"[؀-ۿ]")
# Arabic letters -> Latin consonant classes (vowels, glottal stops and weak letters dropped)
_AR = {"ب": "b", "ت": "t", "ث": "t", "ج": "j", "ح": "h", "خ": "k", "د": "d", "ذ": "z", "ر": "r", "ز": "z", "س": "s",
       "ش": "s", "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "غ": "j", "ف": "f", "ق": "k", "ك": "k", "ل": "l", "م": "m",
       "ن": "n", "ه": "h", "ة": "", "ع": "", "ء": "", "ا": "", "أ": "", "إ": "", "آ": "", "ى": "", "ي": "", "و": "",
       "ئ": "", "ؤ": ""}
_LATIN_DIGRAPHS = (("sch", "s"), ("ch", "s"), ("sh", "s"), ("kh", "k"), ("gh", "g"), ("ph", "f"), ("th", "t"),
                   ("dh", "d"), ("ck", "k"), ("ou", ""), ("q", "k"), ("c", "k"), ("x", "ks"), ("v", "f"), ("p", "b"),
                   ("g", "j"))
# Arabic business words that are not part of a name (the Latin side drops its own through org_key)
_AR_GENERIC = {"شركه", "شركة", "مؤسسه", "مؤسسة", "مصنع", "معمل", "معامل", "لصاحبها", "لصاحبه", "التجاريه", "التجارية",
               "للتجاره", "للتجارة", "والصناعه", "والصناعة", "للصناعه", "للصناعة", "الصناعيه", "الصناعية", "العامه",
               "العامة", "والتجاره", "والتجارة", "ش", "م", "ل", "شمل", "شمم", "اخوان", "واولاده", "وشركاه"}


def skeleton(token: str) -> str:
    """Consonant skeleton of one word, comparable across scripts: 'Massabki' / 'مسابكي' -> 'msbk'."""
    if _ARABIC.search(token):
        word = token[2:] if token.startswith("ال") and len(token) > 4 else token  # definite article
        word = word[:-1] if len(word) > 2 and word.endswith("ه") else word  # a folded final 'ة' ('زحلة' -> 'زحله')
        out = "".join(_AR.get(ch, "") for ch in word)
    else:
        word = _fold(token).replace(" ", "")
        for a, b in _LATIN_DIGRAPHS:
            word = word.replace(a, b)
        out = re.sub(r"[aeiouyw]", "", word) if len(word) > 2 else word
    return re.sub(r"(.)\1+", r"\1", out)  # 'ss' -> 's'


def _initials(names: list[str]) -> set[str]:
    """'United Commercial Assurance SAL' -> {'uca'}: the initials of a Latin name (legal forms dropped)."""
    out = set()
    for name in names:
        if _ARABIC.search(name):
            continue
        words = [w for w in _fold(name).split() if w not in ("sal", "sarl", "s", "a", "l", "co", "and", "of", "the")]
        if 2 <= len(words) <= 6:
            out.add("".join(w[0] for w in words))
    return out


def phone_key(raw: str | None) -> str | None:
    """Lebanese national number of a published phone: '+961 1 748 061', '(01) 748061', '01-748061' -> '1748061'."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("961"):
        digits = digits[3:]
    digits = digits.lstrip("0")
    return digits if 6 <= len(digits) <= 8 else None


# Generic business / sector words (and their Latin transliterations of Arabic words): never a name's identity
_GENERIC_WORDS = {"school", "schools", "college", "ecole", "center", "centre", "mills", "mill", "mattahen", "matahen",
                  "mattaheen", "laiterie", "dairy", "dairies", "hotel", "hotels", "restaurant", "pharmacy",
                  "pharmacie", "clinic", "clinique", "hospital", "hopital", "trading", "industries", "industry",
                  "industrial", "foods", "food", "bakery", "bakeries", "sweets", "factory", "group", "holding",
                  "company", "services", "service", "solutions", "systems", "technology", "technologies",
                  "international", "general", "national", "lebanon", "lebanese", "beirut", "bank", "insurance",
                  "reinsurance", "brokers", "broker", "agency", "consultants", "consulting", "contracting",
                  "engineering", "medical", "store", "stores", "shop", "market", "supermarket", "gallery",
                  "construction", "real", "estate", "properties", "development", "logistics", "shipping",
                  "transport", "computers", "cell", "mobile", "academy", "institute", "university", "مطاحن",
                  "مدرسه", "مدرسة", "مستشفى", "صيدليه", "صيدلية", "فندق", "مطعم", "البان", "واجبان", "حلويات",
                  "افران", "تامين", "للتامين", "بنك", "مصرف", "لبنان", "الدوليه", "الدولية", "العربيه", "العربية"}


def _name_skeletons(name: str, *, arabic_only: bool = False) -> set[str]:
    """Skeletons of a name's distinctive words (legal forms, generic and sector words dropped)."""
    words = [w for w in org_key(name).split() if w not in _AR_GENERIC and _fold(w) not in _GENERIC_WORDS
             and (not arabic_only or _ARABIC.search(w))]
    return {s for w in words if len(s := skeleton(w)) >= 3}


@dataclass
class CompanyContext:
    company: Company
    full: set[str]
    core: set[str]
    acronyms: set[str]
    identifiers: set[tuple[str, str]]
    phones: set[str]
    latin_skeletons: set[str]  # the company's distinctive Latin words, as skeletons
    town: set[str] = field(default_factory=set)


def context(db: Session, company: Company) -> CompanyContext:
    names = company_names(db, company) + list(db.scalars(select(CompanyAlias.alias).where(
        CompanyAlias.company_id == company.id)))
    full, core, acronyms = keys_of(names)
    identifiers = set(db.execute(select(CompanyIdentifier.scheme, CompanyIdentifier.value).where(
        CompanyIdentifier.company_id == company.id)).all())
    phones = {k for p in db.scalars(select(Phone.normalized_phone).where(Phone.company_id == company.id,
                                                                         Phone.person_id.is_(None)))
              if (k := phone_key(p))}
    if k := phone_key(company.primary_phone):
        phones.add(k)
    latin = set()
    for v in [v for n in names for v in name_variants(n) if not _ARABIC.search(v)][:1]:  # the main Latin name
        latin |= _name_skeletons(v)
    town = {skeleton(w) for w in _fold(company.headquarters_city or "").split() if len(w) > 2}
    return CompanyContext(company, full, core, acronyms, identifiers, phones, latin, town)


def match(ctx: CompanyContext, record: Record) -> tuple[int | None, str]:
    """(confidence, stage); confidence None with stage 'possible:...' for a weak signal never applied."""
    if ctx.identifiers & set(record.identifiers.items()):
        return 97, "identifier"
    full, core, acronyms = keys_of(record.org)
    group_mismatch = any(_groupish(k) for k in full) and not any(_groupish(k) for k in ctx.full)
    domain = ctx.company.domain and record.domains[:1] and company_domain(record.domains[0]) == ctx.company.domain
    named = 88 if full & ctx.full else 80 if core & ctx.core or acronyms & ctx.acronyms else None
    if named and group_mismatch:
        return None, "group_mismatch"  # 'X Group' is not 'X'
    if domain:
        return (95 if named else 92), "domain"
    if named:
        return named, "name"
    if group_mismatch:
        return None, "group_mismatch"
    if any(set(k.split()) > set(own.split()) and any(_fold(t) not in _GENERIC_WORDS and t not in _AR_GENERIC
                                                     for t in set(k.split()) - set(own.split()))
           for k in full for own in ctx.full):
        return None, "related_entity"  # 'Byblos Invest Bank' is not 'Byblos Bank' (a shared phone is the group's)
    record_skeletons = set().union(*(_name_skeletons(n) for n in record.org)) if record.org else set()
    shared = ctx.latin_skeletons & record_skeletons
    phone = phone_key((record.facts or {}).get("phone")) or phone_key(record.phone if not record.person else None)
    same_phone = bool(phone and phone in ctx.phones)
    town = {skeleton(w) for w in _fold(str((record.facts or {}).get("city") or "")).split() if len(w) > 2}
    same_town = bool(ctx.town and town & ctx.town)
    if same_phone and (shared or ctx.acronyms & _initials(record.org)):
        return 85, "phone"  # the same number and a shared name element (a word, or 'UCA' = United Commercial A.)
    if same_phone and same_town:
        return 80, "phone_town"  # two independent signals: the same number in the same town
    # transliteration: the Arabic name must contain EVERY distinctive word of the company's Latin name, one of them
    # specific (4+ consonants); generic words ('mills', 'school', 'insurance') never count
    arabic = set().union(*(_name_skeletons(n, arabic_only=True) for n in record.org)) if record.org else set()
    covers = ctx.latin_skeletons and ctx.latin_skeletons <= arabic and any(len(x) >= 4 for x in ctx.latin_skeletons)
    if covers:
        # one distinctive word may sound like a word of another name ('Central' ~ 'كلايمت كونترول'): with a town
        # only, the Arabic name may hold no other distinctive word (the same name both ways)
        if same_phone or same_town and (len(ctx.latin_skeletons) >= 2 or arabic <= ctx.latin_skeletons):
            return 75, "transliteration"
        return None, "possible:transliteration"
    if same_phone:
        return None, "possible:phone"
    return None, "none"


def _language(name: str) -> tuple[str, str]:
    if _ARABIC.search(name):
        return "ar", "arabic"
    if re.search(r"\b(soci[eé]t[eé]|libanaise?|banque|compagnie|g[eé]n[eé]rale|assurances?|[eé]tablissements?)\b",
                 name, re.IGNORECASE):
        return "fr", "french"
    return "en", "source_variant"


def alias_variants(db: Session, company: Company, record: Record) -> list[str]:
    """The spellings of THIS company in a record that matched it. A record may name several organisations (an
    insurer and its broker, a bank and its subsidiary): a Latin spelling must be the company's own name (its full
    or distinctive keys); an Arabic one must transliterate its distinctive words, or be the only Arabic name of a
    record whose every Latin name is the company's (a translation: 'Arabia Insurance' / 'التأمين العربية')."""
    full, core, acronyms = keys_of(company_names(db, company))
    latin_skeletons = set()
    for v in [v for n in company_names(db, company) for v in name_variants(n) if not _ARABIC.search(v)][:1]:
        latin_skeletons |= _name_skeletons(v)
    variants = list(dict.fromkeys(v for name in record.org for v in (name, *name_variants(name))))

    def own(v: str) -> bool:  # the spelling itself, not its parts ('BIOwayste – The University of X' is not X)
        f, c, a = keys_of([v])
        key = org_key(v)
        return bool(key in full or (core_key(key) or "") in core or a & acronyms)

    latin = [v for v in variants if not _ARABIC.search(v) and org_key(v)]
    arabic = [v for v in variants if _ARABIC.search(v) and not re.search(r"[A-Za-z]", v)]
    single = bool(latin) and all(own(v) for v in latin)
    kept = [v for v in latin if own(v)]
    for v in arabic:  # every distinctive Latin word transliterated (one shared word may be a coincidence)
        if latin_skeletons and latin_skeletons <= _name_skeletons(v, arabic_only=True) or \
                single and len({org_key(a) for a in arabic}) == 1:
            kept.append(v)
    return kept


def learn_aliases(db: Session, company: Company, record: Record, source_id: int | None, confidence: int) -> int:
    """A strong match teaches the company the source's spellings of ITS name (its Arabic / French name...), never
    another organisation the record also names. Never overwrites a manual alias; never from a weak match."""
    if confidence < 88:
        return 0
    from app.services.company_search import skeleton_key

    added = 0
    for name in [alias_variants(db, company, record)]:
        for variant in name:
            key = org_key(variant)
            if len(key) < 3 or set(key.split()) & GROUP_WORDS and not _groupish(" ".join(keys_of([company.name])[0])):
                continue
            language, kind = _language(variant)
            result = db.execute(insert(CompanyAlias).values(
                company_id=company.id, alias=variant[:300], normalized_alias=key[:300], language=language,
                skeleton_key=(skeleton_key(variant) or "")[:300] or None,
                alias_type=kind, source_id=source_id, confidence=confidence).on_conflict_do_nothing()
                .returning(CompanyAlias.id))
            added += result.first() is not None
    return added
