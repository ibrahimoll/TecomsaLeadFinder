"""Wikidata people of a company (free, open data; the public API, never a scan of all of Wikidata).

    company -> its Wikidata item, resolved strictly first:
                 the item's official website (P856) is the company's domain, or
                 its label / alias is the company's name AND the item is in Lebanon (P17 / P159)
            -> that item's OWN people claims only: CEO (P169), chairperson (P488), founder (P112),
               director / manager (P1037), board member (P3320); each person must be a human (P31 = Q5)
            -> end date (P582) -> former; otherwise not confirmed (Wikidata is not dated proof of today's role)

Never a parent (P749) or subsidiary's people: a group's CEO is not the Lebanese subsidiary's. A Lebanese company
(a store, a franchise, a branch) only ever gets the people of an item located IN LEBANON: nike.com's item is Nike Inc.,
whose executives are not the Lebanese store's (the website matched a foreign brand: foreign_brand). Answers are cached
(external_search_cache, provider "wikidata") for CACHE_DAYS.
"""

import logging
import re
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Source
from app.services.normalization import company_domain
from app.services.people.candidate import PersonCandidate
from app.services.people.external.lebanon.records import Record, candidate, company_names, keys_of
from app.services.people.external.search import cached_json

logger = logging.getLogger("leadfinder.people.wikidata")
API = "https://www.wikidata.org/w/api.php"
CACHE_DAYS = 30
LEBANON = "Q822"
ROLES = {"P169": "Chief Executive Officer", "P488": "Chairperson", "P112": "Founder", "P1037": "Director / Manager",
         "P3320": "Board Member"}
QUALITY = 75
# Wikimedia's API etiquette: an identifying User-Agent, one request at a time, Retry-After honoured.
USER_AGENT = "TECOMSA-LeadFinder/1.0 (https://tecomsa.me; people research)"
MIN_INTERVAL = 1.0
_lock = threading.Lock()
_last = [0.0]


def _api(http, params: dict) -> dict:
    for attempt in range(3):
        with _lock:
            wait = _last[0] + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            r = http.get(API, params={**params, "format": "json", "maxlag": 5},
                         headers={"User-Agent": USER_AGENT})
            _last[0] = time.monotonic()
        if r.status_code in (429, 503) and attempt < 2:
            retry = r.headers.get("retry-after", "")
            time.sleep(min(float(retry) if retry.isdigit() else 5 * (attempt + 1), 30))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("unreachable")


def _ids(claims: dict, prop: str) -> list[str]:
    return [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims.get(prop, [])
            if c.get("mainsnak", {}).get("datavalue", {}).get("type") == "wikibase-entityid"]


def _labels(entity: dict) -> list[str]:
    names = [v["value"] for v in (entity.get("labels") or {}).values()]
    names += [a["value"] for values in (entity.get("aliases") or {}).values() for a in values]
    return names


def entity_for(db: Session, http, company: Company, *, second_language: bool = True) -> dict | None:
    """The company's own Wikidata item (strict), or None. For a Lebanese company, an item located elsewhere whose
    website is the company's is returned as {"foreign_brand": True}: the domain is a foreign organisation's."""
    from app.services.people.external.lebanon.pack import is_lebanese

    lebanese = is_lebanese(company)
    full, core, _ = keys_of(company_names(db, company))

    def search():
        found: list[str] = []
        # English first; Arabic only for an Arabic name, French only when English knows nothing
        languages = ["en"] + (["ar"] if re.search(r"[\u0600-\u06FF]", company.name) else ["fr"])
        if not second_language:  # one request (a direct search): the name's own script
            languages = languages[1:] if languages[1] == "ar" else languages[:1]
        for language in languages:
            if language == "fr" and found:
                break
            data = _api(http, {"action": "wbsearchentities", "search": company.name[:200], "language": language,
                               "type": "item", "limit": 7})
            found += [hit["id"] for hit in data.get("search", []) if hit["id"] not in found]
        return found

    ids, _ = cached_json(db, "wikidata", f"search:{company.name}", CACHE_DAYS, search)
    if not ids:
        return None
    entities, _ = cached_json(db, "wikidata", f"entities:{'|'.join(ids[:20])}", CACHE_DAYS, lambda: _api(http, {
        "action": "wbgetentities", "ids": "|".join(ids[:20]), "props": "labels|aliases|claims",
        "languages": "en|fr|ar"}).get("entities", {}))
    # headquarters given as a city ("Beirut") rather than a country: the city's own country decides
    cities = sorted({c for qid in ids for c in _ids((entities.get(qid) or {}).get("claims") or {}, "P159")
                     if c != LEBANON})
    city_country = {}
    if cities:
        places, _ = cached_json(db, "wikidata", f"places:{'|'.join(cities[:50])}", CACHE_DAYS, lambda: _api(http, {
            "action": "wbgetentities", "ids": "|".join(cities[:50]), "props": "claims"}).get("entities", {}))
        city_country = {c: _ids((places.get(c) or {}).get("claims") or {}, "P17") for c in cities}
    foreign = None
    for qid in ids:
        entity = entities.get(qid) or {}
        claims = entity.get("claims") or {}
        sites = [c["mainsnak"].get("datavalue", {}).get("value") for c in claims.get("P856", [])]
        countries = set(_ids(claims, "P17")) | {k for c in _ids(claims, "P159")
                                                for k in ([c] if c == LEBANON else city_country.get(c, []))}
        in_lebanon = LEBANON in countries
        named = keys_of(_labels(entity))[:2]
        is_named = bool(named[0] & full or named[1] & core)
        if company.domain and any(company_domain(s) == company.domain for s in sites if isinstance(s, str)):
            if not lebanese or in_lebanon or (not countries and is_named):
                return {"id": qid, **entity, "match": 92}
            if countries:  # located abroad: the domain is a foreign organisation's (unless a Lebanese item matches)
                foreign = foreign or {"id": qid, "foreign_brand": True}
            continue
        if is_named and in_lebanon:
            return {"id": qid, **entity, "match": 85}
    return foreign


def people(db: Session, http, company: Company, stats) -> list[PersonCandidate]:
    entity = entity_for(db, http, company)
    if entity is None:
        stats["wikidata_no_entity"] += 1
        return []
    if entity.get("foreign_brand"):
        stats["foreign_brand_domain"] = 1  # the website is a foreign organisation's: none of its people are ours
        return []
    stats["wikidata_entity"] += 1
    claims = entity.get("claims") or {}
    wanted = [(prop, c) for prop in ROLES for c in claims.get(prop, [])
              if c.get("mainsnak", {}).get("datavalue", {}).get("type") == "wikibase-entityid"]
    if not wanted:
        return []
    person_ids = sorted({c["mainsnak"]["datavalue"]["value"]["id"] for _, c in wanted})
    persons, _ = cached_json(db, "wikidata", f"persons:{'|'.join(person_ids[:50])}", CACHE_DAYS, lambda: _api(http, {
        "action": "wbgetentities", "ids": "|".join(person_ids[:50]), "props": "labels|claims",
        "languages": "en|fr|ar"}).get("entities", {}))
    url = f"https://www.wikidata.org/wiki/{entity['id']}"
    source = db.scalar(select(Source).where(Source.url == url).limit(1))
    if source is None:
        label = next(iter(_labels(entity)), entity["id"])
        source = Source(source_type="open_dataset", name=f"Wikidata: {label}"[:300], url=url, publisher="wikidata.org",
                        retrieved_at=datetime.now(timezone.utc), source_quality=QUALITY,
                        metadata_={"connector": "wikidata", "category": "open_data", "entity": entity["id"]})
        db.add(source)
        db.flush()
    found = []
    for prop, claim in wanted:
        pid = claim["mainsnak"]["datavalue"]["value"]["id"]
        person = persons.get(pid) or {}
        if "Q5" not in _ids(person.get("claims") or {}, "P31"):
            continue  # not a human (an organisation as founder / owner)
        labels = person.get("labels") or {}
        name = (labels.get("en") or labels.get("fr") or labels.get("ar") or {}).get("value")
        qualifiers = claim.get("qualifiers") or {}
        ended = qualifiers.get("P582")
        status = "former" if ended else "unknown"
        record = Record(org=[company.name], person=name, title=ROLES[prop], status=status,
                        excerpt=f"Wikidata {entity['id']} ({prop}: {ROLES[prop]}): {name} ({pid})")
        c = candidate(record, company_id=company.id, source_id=source.id, url=url, source_type="open_data",
                      quality=QUALITY, match_confidence=entity["match"], stated=None, category="open_data",
                      document=source.name)
        if c:
            c.raw_metadata["wikidata_person"] = pid
            found.append(c)
    return found
