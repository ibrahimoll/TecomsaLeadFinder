"""LeadFinder industries -> source categories and keywords.

Sources do not label industries the way TECOMSA does. Overture's taxonomy, for
example, has no "food manufacturing" category for Lebanon: food factories are filed as
`manufacturer`, `industrial_company`, `dairy_farm`, `bottled_water_company`… So an
industry is matched by evidence tiers, structured category first, name last:

  category     a category that means this industry (food_manufacturer, winery…)
  industrial   a generic manufacturing category + a product keyword in the name
  producer     an agricultural producer category (dairy farm; farm + product keyword)
  name         only the name: a product keyword + a different production keyword
               ("Bakalian Flour Mills"), with a neutral or missing category
  retail_name  as `name`, but the category is a shop that may make its own goods
               (bakery, chocolatier, candy store): kept, but never above Low confidence

Consumer venues and stores (restaurants, cafes, supermarkets, grocery stores, caterers,
delivery) and, for food, other kinds of makers never match. When such a record's name
looks like a match ("Chicken Factory", a fast-food restaurant) it is reported as a
wrong-industry rejection instead of being silently dropped.

Custom industries ("Plastic packaging manufacturer") match their words against the
name and the category path. Keep this table practical; extend it as real searches
show gaps.
"""

import csv
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

# Generic "makes things" categories in the Overture taxonomy.
INDUSTRIAL = frozenset({"manufacturer", "industrial_company", "commercial_industrial"})
# Consumer-facing venues and stores: never a manufacturer on their own.
CONSUMER = frozenset(
    {"restaurant", "cafe", "coffee_shop", "bar", "lounge", "fast_food_restaurant", "food_truck_stand",
     "smoothie_juice_bar", "non_alcoholic_beverage_venue", "alcoholic_beverage_venue", "sandwich_shop",
     "hotel", "lodging", "shopping_mall", "clothing_store", "grocery_store", "supermarket", "hypermarket",
     "convenience_store", "beauty_salon", "event_or_party_service", "caterer",
     "food_delivery_service"}
)
# Top-level taxonomy branches of consumer places. A place filed deeper in one of them
# (food_and_drink > casual_eatery > …) is a venue or a store; the bare root is neutral.
CONSUMER_ROOTS = frozenset({"food_and_drink", "shopping"})
# Shops that often make what they sell: a production word in the name keeps them as weak
# (low-confidence) candidates instead of rejecting them.
MAKER_SHOPS = frozenset(
    {"bakery", "candy_store", "chocolatier", "patisserie_cake_shop", "cake_shop", "pastry_shop", "dessert_shop",
     "butcher_shop", "cheese_shop", "coffee_roastery", "dairy_store", "confectionery"}
)
# Agricultural producers: food, but not manufacturing in the industrial sense.
PRODUCERS = frozenset({"farm", "urban_farm", "agricultural_service"})

TIER_POINTS = {"category": 3, "industrial": 2, "producer": 1, "name": 1, "retail_name": 0}
_TIER_RANK = {"category": 3.0, "industrial": 2.0, "producer": 1.5, "name": 1.0, "retail_name": 0.5}

# Specific non-food makers: a "paper mill" or "metal fabricator" is never a food manufacturer.
NON_FOOD_MAKERS = frozenset(
    {"paper_mill", "metal_fabricator", "plastic_manufacturer", "textile_manufacturer", "apparel_manufacturer",
     "glass_manufacturer", "jewelry_and_watches_manufacturer", "machinery_and_tool_manufacturer",
     "industrial_equipment_manufacturer", "vehicle_manufacturer", "auto_manufacturer", "appliance_manufacturer",
     "furniture_manufacturer", "mattress_manufacturing", "chemical_plant"}
)

PRODUCTION = r"factor(y|ies)|industr|manufactur|\bmills?\b|roaster|roastery|plant\b|producer|production|processing|packing|\bfabric|مصنع|مصانع|معمل|معامل|صناع|مطحن|مطاحن|محمص|محامص|معصر|منجر"


def _label(node: str) -> str:
    return node.replace("_", " ")


@dataclass(frozen=True)
class Match:
    tier: str  # see TIER_POINTS
    reason: str

    @property
    def score(self) -> float:
        """Ranking weight (best evidence first)."""
        return _TIER_RANK[self.tier]


@dataclass(frozen=True)
class IndustryProfile:
    key: str
    label: str
    strong: frozenset[str] = frozenset()  # taxonomy nodes that directly mean this industry
    industrial: frozenset[str] = INDUSTRIAL  # generic categories that qualify with a product keyword
    producer: frozenset[str] = frozenset()  # producer categories that qualify with a product keyword
    producer_strong: frozenset[str] = frozenset()  # producer categories that qualify on their own
    product: str | None = None  # regex on the name (lower-case)
    production: str | None = PRODUCTION  # regex on the name; None disables name-only matches
    exclude: frozenset[str] = CONSUMER
    group: str = "Featured"  # heading the industry is listed under
    _product_re: re.Pattern | None = field(init=False, default=None, compare=False)
    _production_re: re.Pattern | None = field(init=False, default=None, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_product_re", re.compile(self.product) if self.product else None)
        object.__setattr__(self, "_production_re", re.compile(self.production) if self.production else None)

    def _name_words(self, text: str) -> tuple[re.Match | None, re.Match | None]:
        """Product keyword, and a production keyword that is a different word ("roastery" is not both)."""
        product = self._product_re.search(text) if self._product_re else None
        if not product or not self._production_re:
            return product, None
        rest = text[: product.start()] + " " * (product.end() - product.start()) + text[product.end():]
        return product, self._production_re.search(rest)

    def mentions(self, text: str) -> bool:
        """Whether a product description is about this industry."""
        return bool(self._product_re and self._product_re.search(text.lower()))

    def _venue(self, nodes: set[str]) -> str | None:
        """The consumer venue / store category of the place, if it is one."""
        if self.exclude & nodes:
            return sorted(self.exclude & nodes)[0]
        if self.exclude and CONSUMER_ROOTS & nodes:
            deeper = nodes - CONSUMER_ROOTS - MAKER_SHOPS
            if deeper:
                return sorted(deeper)[0]
        return None

    def score(self, name: str, nodes: set[str]) -> Match | None:
        """The industry evidence when the place belongs to this industry, else None."""
        if self.strong & nodes:
            return Match("category", f"Category: {_label(sorted(self.strong & nodes)[0])}")
        if self.exclude & nodes:
            return None
        text = name.lower()
        product, production = self._name_words(text)
        if product and self.industrial & nodes:
            node = sorted(self.industrial & nodes)[0]
            return Match("industrial", f"{_label(node).capitalize()} named “{product.group(0).strip()}”")
        if self.producer_strong & nodes:
            return Match("producer", f"Producer category: {_label(sorted(self.producer_strong & nodes)[0])}")
        if product and self.producer & nodes:
            node = sorted(self.producer & nodes)[0]
            return Match("producer", f"{_label(node).capitalize()} named “{product.group(0).strip()}”")
        if not (product and production):
            return None
        words = f"“{product.group(0).strip()}” and “{production.group(0).strip()}”"
        if self.exclude and MAKER_SHOPS & nodes:
            shop = _label(sorted(MAKER_SHOPS & nodes)[0])
            return Match("retail_name", f"Name mentions {words}, but the category is a shop ({shop})")
        if self._venue(nodes):
            return None
        return Match("name", f"Name mentions {words} (no manufacturing category)")

    def reject(self, name: str, nodes: set[str]) -> str | None:
        """Why a place whose name looks like this industry is not one (category evidence), else None."""
        text = name.lower()
        product, production = self._name_words(text)
        if not product or not (production or self.industrial & nodes):
            return None
        venue = self._venue(nodes)
        if venue is None:
            return None
        kind = "a consumer venue or store" if venue not in NON_FOOD_MAKERS else "another kind of manufacturer"
        return f"Category is {_label(venue)}: {kind}, not {self.label.lower()}."


FOOD = (
    r"\bfoods?\b|food ?stuff|dairy|dairies|\bmilk|cheese|laban|flour|frozen|snack|conserve|cann(ed|ing|ery)|"
    r"biscuit|chocolat|confection|sweets|candies|candy|toffee|dragee|dragée|pastry|patisserie|bakeries|\bbread|"
    r"croissant|pasta|noodle|spice|olive oil|\bmeat|poultry|chicken|coffee|roast|honey|\bmills\b|taghzi|matahen|mattahen|"
    r"pickles|tahini|halawa|halva|sugar|juice|food ?tech|"
    r"اغذي|أغذي|غذائي|البان|ألبان|اجبان|أجبان|حليب|طحين|حلويات|شوكولا|قهوة|محمص|معجنات|خبز|مونة|مونه|زيت ?ال?زيتون|للزيتون|لحوم|دجاج|بهارات|عسل|"
    r"مكسرات|طحينة|حلاوة|مخلل|كونسروة"
)

INDUSTRIES: tuple[IndustryProfile, ...] = (
    IndustryProfile(
        "food_manufacturing", "Food Manufacturing",
        strong=frozenset({"food_manufacturer", "food_processing", "food_production", "flour_mill",
                          "bakery_manufacturer", "meat_processing", "food_beverage_manufacturer"}),
        # Distributors and wholesalers qualify only with a production word (see Distribution).
        producer=PRODUCERS,
        producer_strong=frozenset({"dairy_farm"}),
        product=FOOD,
        exclude=CONSUMER | NON_FOOD_MAKERS,
    ),
    IndustryProfile(
        "beverage_manufacturing", "Beverage Manufacturing",
        strong=frozenset({"bottled_water_company", "brewery", "distillery", "winery", "beverage_manufacturer"}),
        industrial=INDUSTRIAL | {"food_beverage_distributor"},
        product=r"water|juice|beverage|drinks?\b|wine|\barak|arak\b|beer|brew|distill|soda|cola|مياه|عصير|مشروب|نبيذ|عرق|بيرة",
    ),
    IndustryProfile(
        "furniture_manufacturing", "Furniture Manufacturing",
        strong=frozenset({"furniture_manufacturer", "mattress_manufacturing"}),
        industrial=INDUSTRIAL | {"carpenter"},
        product=r"furniture|wood|kitchen|mattress|sofa|upholster|cabinet|joinery|أثاث|اثاث|مفروشات|خشب|اخشاب|أخشاب|موبيليا|مطابخ",
    ),
    IndustryProfile(
        "packaging", "Packaging",
        strong=frozenset({"plastic_manufacturer", "paper_mill", "packaging_service", "packaging_supply"}),
        product=r"packag|carton|paper|plastic|\bbags?\b|containers?|\bpack\b|bottles?|labels?|تغليف|كرتون|ورق|بلاستيك|نايلون|أكياس|اكياس|عبوات",
    ),
    IndustryProfile(
        "pharmaceutical", "Pharmaceutical",
        strong=frozenset({"pharmaceutical_company", "pharmaceutical_manufacturer"}),
        product=r"pharma|laborator|\blabs?\b|medic|drug|cosmetic|أدوية|ادوية|مختبر|صيدل|مستحضرات",
    ),
    IndustryProfile(
        "restaurants", "Restaurants",
        strong=frozenset({"restaurant", "casual_eatery", "fast_food_restaurant"}),
        product=None, production=None, exclude=frozenset(),
    ),
    IndustryProfile(
        "hotels", "Hotels",
        strong=frozenset({"hotel", "resort", "motel", "inn", "lodge", "service_apartment", "bed_and_breakfast", "hostel",
                          "beach_resort", "ski_resort"}),
        product=None, production=None, exclude=frozenset(),
    ),
    IndustryProfile(
        "construction", "Construction",
        strong=frozenset({"building_or_construction_service", "contractor", "engineering_service", "home_developer",
                          "builder", "general_contractor", "construction_company"}),
        product=r"construct|contract|engineering|concrete|steel|building|مقاولات|انشاء|إنشاء|هندس|باطون|بناء",
    ),
    IndustryProfile(
        "retail", "Retail",
        strong=frozenset({"department_store", "shopping_mall", "grocery_store", "supermarket", "convenience_store",
                          "discount_store", "clothing_store", "electronics_store", "furniture_store",
                          "hardware_home_and_garden_store", "shoe_store", "fashion_and_apparel_store"}),
        product=None, production=None, exclude=frozenset(),
    ),
    IndustryProfile(
        "logistics", "Logistics",
        strong=frozenset({"freight_and_cargo_service", "freight_forwarding_agency", "warehouse", "b2b_storage",
                          "shipping_center", "vehicle_shipping", "b2b_transportation_and_storage_service",
                          "courier_service", "moving_company", "trucking_company", "logistics_service"}),
        product=r"logistic|freight|cargo|shipping|forward|transport|courier|warehous|شحن|نقل|لوجست|تخزين",
        production=None,
    ),
    IndustryProfile(
        "automotive", "Automotive",
        strong=frozenset({"auto_dealer", "auto_company", "auto_manufacturer", "car_dealer", "auto_parts_store",
                          "automotive_parts_and_accessories"}),
        product=r"\bauto|motors?\b|\bcars?\b|vehicle|tyres?|tires?|سيارات|اطارات|إطارات",
        production=None,
    ),
    IndustryProfile(
        "real_estate", "Real Estate",
        strong=frozenset({"real_estate_service", "real_estate_agent", "home_developer", "commercial_real_estate",
                          "property_management", "real_estate_investment"}),
        product=None, production=None, exclude=frozenset(),
    ),
    IndustryProfile(
        "distribution", "Distribution",
        strong=frozenset({"supplier_or_distributor", "wholesaler", "food_beverage_distributor", "wholesale_grocer",
                          "electronic_equipment_supplier", "restaurant_equipment_and_supply", "hotel_supply_service",
                          "beauty_product_supplier", "metal_supplier", "meat_wholesaler"}),
        product=r"distribut|trading|wholesale|import|supplies|supply|توزيع|تجارة|التجارية|استيراد|جملة",
        production=None,
    ),
)

# Every business category in Overture's place taxonomy (release 2026-09-23.0, from
# github.com/OvertureMaps/docs static/taxonomy/), offered as a plain category industry: a place
# matches when the category is anywhere on its taxonomy path, so a parent covers all of its
# subcategories. Geographic entities and cultural/historic sites are left out (not businesses).
_TAXONOMY = Path(__file__).with_name("overture_taxonomy.csv")


def _category_industries() -> tuple[IndustryProfile, ...]:
    with _TAXONOMY.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    roots = {r["primary"]: r["displayName"] for r in rows if " > " not in r["taxonomy"]}
    return tuple(
        IndustryProfile(
            r["primary"], r["displayName"], strong=frozenset({r["primary"]}),
            product=None, production=None, exclude=frozenset(),
            group=roots[r["taxonomy"].split(" > ")[0]],
        )
        for r in rows
    )


INDUSTRIES = INDUSTRIES + _category_industries()
INDUSTRY_BY_KEY = {p.key: p for p in INDUSTRIES}
assert len(INDUSTRY_BY_KEY) == len(INDUSTRIES), "industry keys must be unique"

_STOPWORDS = frozenset(
    {"and", "or", "of", "in", "the", "for", "a", "an", "companies", "company", "lebanon", "lebanese", "business",
     "businesses", "services", "service", "firms", "firm"}
)


def _stem(word: str) -> str:
    for suffix in ("ies", "ers", "ing", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


@dataclass(frozen=True)
class CustomProfile:
    """Free-text industry: every meaningful word must appear in the name or category path
    (one may be missing when there are three or more)."""

    text: str

    @property
    def key(self) -> None:
        return None

    @property
    def label(self) -> str:
        return " ".join(self.text.split())[:150]

    @property
    def words(self) -> list[str]:
        words = [w for w in re.findall(r"\w+", self.text.lower()) if w not in _STOPWORDS and len(w) > 1]
        return [_stem(w) for w in words]

    def score(self, name: str, nodes: set[str]) -> Match | None:
        words = self.words
        if not words:
            return None
        categories = " ".join(_label(n) for n in nodes)
        hits = [w for w in words if w in f"{name.lower()} {categories}"]
        needed = len(words) if len(words) < 3 else len(words) - 1
        if len(hits) < needed:
            return None
        tier = "industrial" if any(w in categories for w in hits) else "name"
        return Match(tier, f"Matches “{', '.join(hits)}”" + ("" if tier == "industrial" else " (name only)"))

    def reject(self, name: str, nodes: set[str]) -> str | None:
        return None

    def mentions(self, text: str) -> bool:
        return any(w in text.lower() for w in self.words)


# ---- LeadFinder's normalized industries ---------------------------------------------------------------
#
# A deliberately small taxonomy (companies.industry). The source's own category is kept as
# companies.sub_industry (raw), so a later classifier can re-map without losing anything.


@dataclass(frozen=True)
class CompositeProfile:
    """An industry made of several profiles (e.g. Food & Beverage); the best member's evidence wins."""

    label: str
    members: tuple[IndustryProfile, ...]

    @property
    def key(self) -> str:
        return self.label

    def score(self, name: str, nodes: set[str]) -> Match | None:
        matches = [m for p in self.members if (m := p.score(name, nodes))]
        return max(matches, key=lambda m: m.score) if matches else None

    def reject(self, name: str, nodes: set[str]) -> str | None:
        return next((r for p in self.members if (r := p.reject(name, nodes))), None)

    def mentions(self, text: str) -> bool:
        return any(p.mentions(text) for p in self.members)


# Branches of the place taxonomy that are not businesses LeadFinder sells to.
NON_BUSINESS = frozenset({"community_and_government", "sports_and_recreation", "arts_and_entertainment", "park",
                          "religious_organization", "place_of_worship", "government_office", "military_site"})


@dataclass(frozen=True)
class AnyBusinessProfile:
    """No industry requested: any business, never a park, a ministry or a place of worship."""

    label: str = "Any industry"

    @property
    def key(self) -> None:
        return None

    def score(self, name: str, nodes: set[str]) -> Match | None:
        if nodes & NON_BUSINESS:
            return None
        return Match("category" if nodes else "name", "Any business")

    def reject(self, name: str, nodes: set[str]) -> str | None:
        return None

    def mentions(self, text: str) -> bool:
        return True


def _category(label: str, *nodes: str, product: str | None = None) -> IndustryProfile:
    """A category industry: matches when any node is on the place's taxonomy path (a parent covers its children)."""
    return IndustryProfile(label, label, strong=frozenset(nodes), product=product, production=None,
                           exclude=frozenset())


_MANUFACTURER_NODES = frozenset(
    {n for n in INDUSTRY_BY_KEY if n.endswith(("_manufacturer", "_manufacturing", "_mill", "_plant"))}
    | INDUSTRIAL | {"manufacturer", "winery", "brewery", "distillery", "bottled_water_company"}
)

# Order matters for normalize_industry(): the most specific industries first.
NORMALIZED: tuple[IndustryProfile | CompositeProfile, ...] = (
    replace(INDUSTRY_BY_KEY["food_manufacturing"], key="Food Manufacturing", label="Food Manufacturing"),
    CompositeProfile("Food & Beverage", (
        INDUSTRY_BY_KEY["food_manufacturing"], INDUSTRY_BY_KEY["beverage_manufacturing"],
        _category("Food & beverage distribution", "food_beverage_distributor", "wholesale_grocer", "meat_wholesaler"),
    )),
    replace(INDUSTRY_BY_KEY["pharmaceutical"], key="Pharmaceutical", label="Pharmaceutical"),
    _category("Insurance", "insurance_agency", "insurance_company", product=r"insurance|assurance|تأمين|تامين"),
    _category("Financial Services", "financial_service", "bank", "bank_or_credit_union"),
    _category("Telecom", "telecommunications_service", "telecommunications_company", "mobile_phone_store"),
    _category("Technology", "information_technology_company", "software_development", "technical_service",
              "computer_hardware_company", "it_service_and_computer_repair", "it_consultant"),
    replace(INDUSTRY_BY_KEY["logistics"], key="Logistics", label="Logistics"),
    _category("Wholesale", "wholesaler", "wholesale_grocer", "meat_wholesaler", "computer_wholesaler"),
    replace(INDUSTRY_BY_KEY["distribution"], key="Distribution", label="Distribution"),
    replace(INDUSTRY_BY_KEY["automotive"], key="Automotive", label="Automotive",
            strong=INDUSTRY_BY_KEY["automotive"].strong | {"vehicle_dealer", "vehicle_service"}),
    replace(INDUSTRY_BY_KEY["construction"], key="Construction", label="Construction"),
    replace(INDUSTRY_BY_KEY["real_estate"], key="Real Estate", label="Real Estate",
            strong=INDUSTRY_BY_KEY["real_estate"].strong | {"housing_or_property_service"}),
    _category("Healthcare", "health_care"),
    _category("Education", "education"),
    _category("Hospitality", "lodging", "food_and_drink"),
    _category("Agriculture", "agricultural_service", "farm", "dairy_farm"),
    IndustryProfile("Manufacturing", "Manufacturing", strong=_MANUFACTURER_NODES, product=None, production=None,
                    exclude=CONSUMER),
    _category("Retail", "shopping"),
    _category("Professional Services", "professional_service", "legal_service", "design_service",
              "corporate_or_business_office", "b2b_service", "media_service", "printing_service"),
)
NORMALIZED_BY_LABEL = {p.label: p for p in NORMALIZED}
OTHER = "Other"
NORMALIZED_LABELS = (*NORMALIZED_BY_LABEL, OTHER)


def _fold(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", text.lower().replace("&", " and ")).split())


_BY_FOLDED = {_fold(p.label): p for p in INDUSTRIES} | {_fold(p.label): p for p in NORMALIZED}


def profile_for(text: str | None) -> IndustryProfile | CompositeProfile | CustomProfile | AnyBusinessProfile:
    """What the user typed -> how sources are matched: a normalized industry ("food & beverage"), a known
    profile or source category ("Winery"), else free text ("plastic packaging")."""
    if not text or not text.strip() or _fold(text) in ("any", "other", "any industry"):
        return AnyBusinessProfile()
    return _BY_FOLDED.get(_fold(text)) or CustomProfile(text)


def normalize_industry(name: str, nodes: set[str]) -> str:
    """The normalized industry of one record, from its categories (first, most specific, match wins)."""
    for profile in NORMALIZED:
        match = profile.score(name, nodes)
        if match and match.tier in ("category", "industrial", "producer"):
            return profile.label
    return OTHER


# Free-text sector labels (Wikidata types, registry / directory sectors) -> category keys the profiles understand.
_LABEL_NODES = (
    (r"\bbank|banking|financial", {"financial_service", "bank"}),
    (r"insurance", {"insurance_agency", "financial_service"}),
    (r"telecom|mobile phone", {"telecommunications_service"}),
    (r"software|information technology|computer|internet|video game", {"information_technology_company",
                                                                        "software_development"}),
    (r"winery|wine", {"winery", "manufacturer"}),
    (r"brewery|beverage|drink", {"beverage_manufacturer", "manufacturer"}),
    (r"food|dairy|confection|bakery", {"food_manufacturer", "manufacturer"}),
    (r"pharmac", {"pharmaceutical_company"}),
    (r"hotel|hospitality", {"lodging", "hotel"}),
    (r"restaurant", {"food_and_drink", "restaurant"}),
    (r"retail|supermarket|department store", {"shopping"}),
    (r"construction|civil engineering|architecture", {"construction_company", "building_or_construction_service"}),
    (r"real estate", {"real_estate_service"}),
    (r"logistic|shipping|transport|airline|mail", {"logistics_service"}),
    (r"publish|journalism|media|advertising|marketing|television|radio", {"media_service"}),
    (r"hospital|health|medical", {"health_care"}),
    (r"universit|school|education", {"education"}),
    (r"manufactur|industr", {"manufacturer"}),
    (r"consult|law firm|accounting|professional", {"professional_service"}),
)


def label_nodes(labels: list[str]) -> set[str]:
    text = " ".join(labels).lower()
    return {n for pattern, nodes in _LABEL_NODES if re.search(pattern, text) for n in nodes}
