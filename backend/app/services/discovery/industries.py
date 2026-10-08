"""LeadFinder industries -> source categories and keywords.

Sources do not label industries the way TECOMSA does. Overture's taxonomy, for
example, has no "food manufacturing" category for Lebanon: food factories are filed as
`manufacturer`, `industrial_company`, `dairy_farm`, `bottled_water_company`… So an
industry is matched by:

  1. strong categories: any node of the place's taxonomy path/alternates   (score 3)
  2. industrial category + a product keyword in the name                   (score 2)
  3. a product keyword + a different production keyword in the name (e.g.
     "Linda Chocolate Factory", "Bakalian Flour Mills")                     (score 1)
Rules 2 and 3 never apply to excluded categories (restaurants, shops, and for food
other kinds of makers such as paper mills).

Custom industries ("Plastic packaging manufacturer") match their words against the
name and the category path. Keep this table practical; extend it as real searches
show gaps.
"""

import re
from dataclasses import dataclass, field

# Generic "makes things" categories in the Overture taxonomy.
INDUSTRIAL = frozenset({"manufacturer", "industrial_company", "commercial_industrial"})
# Consumer-facing venues: never a manufacturer on their own.
CONSUMER = frozenset(
    {"restaurant", "cafe", "coffee_shop", "bar", "lounge", "fast_food_restaurant", "food_truck_stand",
     "smoothie_juice_bar", "non_alcoholic_beverage_venue", "alcoholic_beverage_venue",
     "hotel", "lodging", "shopping_mall", "clothing_store", "grocery_store", "convenience_store", "beauty_salon",
     "event_or_party_service", "food_delivery_service"}
)

# Specific non-food makers: a "paper mill" or "metal fabricator" is never a food manufacturer.
NON_FOOD_MAKERS = frozenset(
    {"paper_mill", "metal_fabricator", "plastic_manufacturer", "textile_manufacturer", "apparel_manufacturer",
     "glass_manufacturer", "jewelry_and_watches_manufacturer", "machinery_and_tool_manufacturer",
     "industrial_equipment_manufacturer", "vehicle_manufacturer", "auto_manufacturer", "appliance_manufacturer",
     "furniture_manufacturer", "mattress_manufacturing", "chemical_plant"}
)

PRODUCTION = r"factor(y|ies)|industr|manufactur|\bmills?\b|roaster|roastery|plant\b|producer|production|processing|packing|\bfabric|مصنع|مصانع|معمل|معامل|صناع|مطحن|مطاحن|محمص|محامص|معصر|منجر"


@dataclass(frozen=True)
class IndustryProfile:
    key: str
    label: str
    strong: frozenset[str] = frozenset()  # taxonomy nodes that directly mean this industry
    industrial: frozenset[str] = INDUSTRIAL  # generic categories that qualify with a product keyword
    product: str | None = None  # regex on the name (lower-case)
    production: str | None = PRODUCTION  # regex on the name; None disables rule 3
    exclude: frozenset[str] = CONSUMER
    _product_re: re.Pattern | None = field(init=False, default=None, compare=False)
    _production_re: re.Pattern | None = field(init=False, default=None, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_product_re", re.compile(self.product) if self.product else None)
        object.__setattr__(self, "_production_re", re.compile(self.production) if self.production else None)

    def score(self, name: str, nodes: set[str]) -> tuple[float, str] | None:
        """(score, reason) when the place belongs to this industry, else None."""
        if self.strong & nodes:
            node = sorted(self.strong & nodes)[0]
            return 3.0, f"Category: {node.replace('_', ' ')}"
        text = name.lower()
        if self.exclude & nodes:
            return None
        product = self._product_re.search(text) if self._product_re else None
        if product and self.industrial & nodes:
            node = sorted(self.industrial & nodes)[0]
            return 2.0, f"{node.replace('_', ' ').capitalize()} named “{product.group(0).strip()}”"
        if product and self._production_re:
            # The production word must be a different word ("roastery" is not both).
            rest = text[: product.start()] + " " * (product.end() - product.start()) + text[product.end():]
            production = self._production_re.search(rest)
            if production:
                return 1.0, f"Name mentions “{product.group(0).strip()}” and “{production.group(0).strip()}”"
        return None


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
        strong=frozenset({"food_manufacturer", "food_processing", "food_production", "dairy_farm", "flour_mill",
                          "bakery_manufacturer", "meat_processing", "food_beverage_manufacturer"}),
        # Distributors and wholesalers qualify only with a production word (see Distribution).
        industrial=INDUSTRIAL | {"agricultural_service"},
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

INDUSTRY_BY_KEY = {p.key: p for p in INDUSTRIES}

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

    def score(self, name: str, nodes: set[str]) -> tuple[float, str] | None:
        words = self.words
        if not words:
            return None
        haystack = f"{name.lower()} {' '.join(n.replace('_', ' ') for n in nodes)}"
        hits = [w for w in words if w in haystack]
        needed = len(words) if len(words) < 3 else len(words) - 1
        if len(hits) < needed:
            return None
        return len(hits) / len(words) * 3, f"Matches “{', '.join(hits)}”"


def profile_for(industry: str | None, custom: str | None) -> IndustryProfile | CustomProfile:
    if industry:
        return INDUSTRY_BY_KEY[industry]
    return CustomProfile(custom or "")
