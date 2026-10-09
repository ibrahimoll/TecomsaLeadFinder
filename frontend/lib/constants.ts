import type {
  CompanySource,
  UserRole,
} from "@/types";

export const USER_ROLES: { value: UserRole; label: string }[] = [
  { value: "ADMIN", label: "Administrator" },
  { value: "SALES_MANAGER", label: "Sales Manager" },
  { value: "SALES_AGENT", label: "Salesperson" },
];

export const ROLE_LABEL: Record<UserRole, string> = {
  ADMIN: "Administrator",
  SALES_MANAGER: "Sales Manager",
  SALES_AGENT: "Salesperson",
};

export const SOURCE_LABEL: Record<CompanySource, string> = {
  MANUAL: "Manual",
  ODOO_IMPORT: "Odoo import",
  DEMO: "Demo data",
  DISCOVERY: "Discovery",
};

export const INDUSTRIES = [
  "Automotive",
  "Banking & Finance",
  "Construction",
  "E-commerce",
  "Education",
  "Food & Beverage",
  "Government",
  "Healthcare",
  "Hospitality",
  "Insurance",
  "Logistics",
  "Manufacturing",
  "Media & Advertising",
  "NGO / Non-profit",
  "Oil & Gas",
  "Pharmaceuticals",
  "Professional Services",
  "Real Estate",
  "Restaurants",
  "Retail",
  "Technology",
  "Telecommunications",
  "Trading & Distribution",
  "Travel & Tourism",
];

// ISO 3166-1 alpha-2 codes; names are rendered with Intl.DisplayNames.
const COUNTRY_CODES =
  "AE AF AL AM AO AR AT AU AZ BA BD BE BF BG BH BI BJ BN BO BR BS BT BW BY BZ CA CD CF CG CH CI CL CM CN CO CR CU CV CY CZ DE DJ DK DO DZ EC EE EG ER ES ET FI FJ FR GA GB GE GH GM GN GQ GR GT GW GY HK HN HR HT HU ID IE IN IQ IR IS IT JM JO JP KE KG KH KM KR KW KZ LA LB LK LR LS LT LU LV LY MA MD ME MG MK ML MM MN MR MT MU MV MW MX MY MZ NA NE NG NI NL NO NP NZ OM PA PE PG PH PK PL PS PT PY QA RO RS RU RW SA SC SD SE SG SI SK SL SN SO SR SS SV SY SZ TD TG TH TJ TM TN TR TT TW TZ UA UG US UY UZ VE VN YE ZA ZM ZW".split(
    " ",
  );

let countryCache: string[] | null = null;
export function countryNames(): string[] {
  if (countryCache) return countryCache;
  const display = new Intl.DisplayNames(["en"], { type: "region" });
  countryCache = COUNTRY_CODES.map((code) => display.of(code) ?? code).sort((a, b) => a.localeCompare(b));
  return countryCache;
}
