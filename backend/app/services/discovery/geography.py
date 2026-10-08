"""Countries and searchable areas (cities / governorates) for discovery and geographic normalization.

A place is in an area when its coordinates fall inside it (radius around a city centre,
or a few non-overlapping boxes approximating a governorate). Only places without
coordinates fall back to their locality/address text (English, French or Arabic names):
text is unreliable when a brand carries a town name ("Rawabi Chtaura" in Beirut).

The boxes are simple approximations; they decide search scope, not official
administrative boundaries. Add a country by adding a Country entry (and its areas).

Country, region (governorate) and city are kept apart: Jounieh is a city in the Mount Lebanon region.
"""

import math
import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Country:
    code: str  # ISO 3166-1 alpha-2
    name: str
    bbox: tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)
    aliases: tuple[str, ...] = ()
    wikidata: str | None = None  # Wikidata item of the country
    geofabrik: str | None = None  # Geofabrik extract path for OpenStreetMap


@dataclass(frozen=True)
class Area:
    key: str
    label: str
    kind: str  # "city" | "governorate" | "text" (an unknown place name: matched on address text only)
    names: tuple[str, ...]
    center: tuple[float, float] | None = None  # (lat, lon) for cities
    radius_km: float = 0.0
    # One or more (min_lat, max_lat, min_lon, max_lon) boxes for a governorate.
    boxes: tuple[tuple[float, float, float, float], ...] = ()
    exclude: tuple[str, ...] = ()  # areas carved out of this one (Beirut inside Mount Lebanon)
    region: str | None = None  # for a city: the label of its governorate
    keys: frozenset[str] = field(init=False, default=frozenset())

    def __post_init__(self) -> None:
        object.__setattr__(self, "keys", frozenset(_fold(n) for n in self.names))


def _fold(text: str) -> str:
    """Lower-case, strip accents/diacritics and Arabic article variants for comparison."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"[^\w\s]|_", " ", text).strip()


COUNTRIES: dict[str, Country] = {
    "LB": Country("LB", "Lebanon", (35.10, 33.05, 36.63, 34.70),
                  aliases=("Lebanon", "Liban", "Lebanese Republic", "Republic of Lebanon", "لبنان", "LB", "LBN"),
                  wikidata="Q822", geofabrik="asia/lebanon"),
}

_LB_AREAS: tuple[Area, ...] = (
    Area("beirut", "Beirut", "city", ("Beirut", "Beyrouth", "بيروت"), center=(33.8938, 35.5018), radius_km=5.5,
         region="Beirut"),
    Area("tripoli", "Tripoli", "city", ("Tripoli", "Trablous", "طرابلس"), center=(34.4367, 35.8497), radius_km=7,
         region="North Lebanon"),
    Area("saida", "Saida", "city", ("Saida", "Saïda", "Sidon", "صيدا"), center=(33.5571, 35.3729), radius_km=6,
         region="South Lebanon"),
    Area("tyre", "Tyre", "city", ("Tyre", "Tyr", "Sour", "صور"), center=(33.2705, 35.2038), radius_km=5,
         region="South Lebanon"),
    Area("zahle", "Zahle", "city", ("Zahle", "Zahlé", "Zahleh", "زحلة", "زحله"), center=(33.8463, 35.9020), radius_km=6,
         region="Bekaa"),
    Area("jounieh", "Jounieh", "city", ("Jounieh", "Juniyah", "جونية", "جونيه"), center=(33.9808, 35.6178), radius_km=5,
         region="Mount Lebanon"),
    Area("byblos", "Byblos (Jbeil)", "city", ("Byblos", "Jbeil", "Jbayl", "جبيل"), center=(34.1230, 35.6519), radius_km=5,
         region="Mount Lebanon"),
    Area("baalbek", "Baalbek", "city", ("Baalbek", "Baalbeck", "Ba`labakk", "بعلبك"), center=(34.0047, 36.2110),
         radius_km=5, region="Baalbek-Hermel"),
    Area("nabatieh", "Nabatieh", "city", ("Nabatieh", "Nabatiye", "Nabatîyé", "النبطية"), center=(33.3772, 35.4836),
         radius_km=5, region="Nabatieh Governorate"),
    Area("batroun", "Batroun", "city", ("Batroun", "Batroûn", "البترون"), center=(34.2553, 35.6581), radius_km=4,
         region="North Lebanon"),
    Area("chtaura", "Chtaura", "city", ("Chtaura", "Chtoura", "Shtaura", "شتورة", "شتوره"), center=(33.8190, 35.8570),
         radius_km=4, region="Bekaa"),
    Area("aley", "Aley", "city", ("Aley", "Alay", "عاليه"), center=(33.8100, 35.6000), radius_km=4,
         region="Mount Lebanon"),
    Area("mount_lebanon", "Mount Lebanon", "governorate",
         ("Mount Lebanon", "Mont-Liban", "Mont Liban", "Jabal Lubnan", "جبل لبنان"),
         boxes=((33.55, 34.18, 35.45, 35.78),), exclude=("beirut",)),
    Area("north", "North Lebanon", "governorate", ("North", "Nord", "الشمال", "محافظة الشمال"),
         boxes=((34.18, 34.52, 35.60, 36.10),)),
    Area("akkar", "Akkar", "governorate", ("Akkar", "عكار"), boxes=((34.45, 34.70, 35.95, 36.45),)),
    Area("bekaa", "Bekaa", "governorate", ("Bekaa", "Beqaa", "Béqaa", "البقاع", "محافظة البقاع"),
         boxes=((33.62, 34.05, 35.78, 36.05), (33.35, 33.62, 35.62, 35.95))),
    Area("baalbek_hermel", "Baalbek-Hermel", "governorate", ("Baalbek-Hermel", "بعلبك الهرمل", "محافظة بعلبك الهرمل"),
         boxes=((33.90, 34.65, 36.05, 36.63),)),
    Area("south", "South Lebanon", "governorate", ("South", "Sud", "الجنوب", "محافظة الجنوب"),
         boxes=((33.05, 33.62, 35.10, 35.42),)),
    Area("nabatieh_gov", "Nabatieh Governorate", "governorate", ("محافظة النبطية",),
         boxes=((33.10, 33.55, 35.42, 35.80),)),
)

AREAS: dict[str, dict[str, Area]] = {"LB": {a.key: a for a in _LB_AREAS}}


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _names_match(area: Area, texts: list[str]) -> bool:
    for text in texts:
        folded = f" {_fold(text)} "
        if any(f" {k} " in folded for k in area.keys):
            return True
    return False


def in_area(area: Area, lat: float | None, lon: float | None, texts: list[str], country: str = "LB") -> bool:
    if area.kind == "text":  # an unknown place: only the record's own address text can say
        return _names_match(area, texts)
    areas = AREAS.get(country, {})
    if any(in_area(areas[k], lat, lon, texts, country) for k in area.exclude if k in areas):
        return False
    if lat is None or lon is None:
        return _names_match(area, texts)
    if area.center:
        return _distance_km(area.center, (lat, lon)) <= area.radius_km
    return any(b[0] <= lat <= b[1] and b[2] <= lon <= b[3] for b in area.boxes)


def canonical_city(country: str, lat: float | None, lon: float | None, locality: str | None) -> str | None:
    """English city name for display/matching: the known city at these coordinates, else one
    named in the locality, else the raw locality."""
    cities = [a for a in AREAS.get(country, {}).values() if a.kind == "city"]
    if lat is not None and lon is not None:
        for area in cities:
            if area.center and _distance_km(area.center, (lat, lon)) <= area.radius_km:
                return area.label
    if locality:
        for area in cities:
            if _names_match(area, [locality]):
                if lat is not None and lon is not None and area.center and                         _distance_km(area.center, (lat, lon)) > max(15.0, 3 * area.radius_km):
                    return None  # the text names a city the place is not in: show nothing rather than a wrong city
                return area.label
    return locality


def find_country(text: str | None) -> Country | None:
    """'Lebanon', 'LB', 'Liban', 'لبنان' -> the Lebanon entry. None for countries not configured."""
    if not text:
        return None
    folded = _fold(text)
    return next((c for c in COUNTRIES.values() if folded in {_fold(a) for a in (c.code, c.name, *c.aliases)}), None)


def find_area(country: str, text: str | None) -> Area | None:
    """The searchable area a user typed ('Beirut', 'Mount Lebanon', 'جونية'); an unknown place name becomes a
    text-only area (matched on address text, never on coordinates)."""
    if not text or not text.strip():
        return None
    folded = _fold(text)
    for area in AREAS.get(country, {}).values():
        if folded in area.keys or folded == _fold(area.label):
            return area
    label = " ".join(text.split())[:120]
    return Area(f"text:{folded}", label, "text", (label,))


def region_for(country: str, lat: float | None, lon: float | None, city: str | None = None) -> str | None:
    """The governorate of a place: from its coordinates, else from a known city name. None when unknown."""
    areas = AREAS.get(country, {})
    if lat is not None and lon is not None:
        for area in areas.values():
            if area.kind == "city" and area.region and area.center and \
                    _distance_km(area.center, (lat, lon)) <= area.radius_km:
                return area.region
        for area in areas.values():
            if area.kind == "governorate" and in_area(area, lat, lon, [], country):
                return area.label
    if city:
        area = find_area(country, city)
        if area is not None and area.kind == "city":
            return area.region
    return None
