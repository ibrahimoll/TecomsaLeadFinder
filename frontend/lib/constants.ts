import type {
  ActivityType,
  CampaignStatus,
  CompanySource,
  Division,
  ImportType,
  OdooStatus,
  UserRole,
} from "@/types";

export const DIVISIONS: { value: Division; label: string }[] = [
  { value: "FRINZO", label: "Frinzo" },
  { value: "ODOO", label: "Odoo ERP" },
  { value: "IT", label: "IT Solutions" },
];

export const DIVISION_LABEL: Record<Division, string> = {
  FRINZO: "Frinzo",
  ODOO: "Odoo ERP",
  IT: "IT Solutions",
};

export const ROLE_SUGGESTIONS: Record<Division, string[]> = {
  FRINZO: ["Marketing Manager", "Customer Service Manager", "E-commerce Manager", "CEO", "Owner"],
  ODOO: ["CEO", "CFO", "Finance Manager", "Operations Manager", "IT Manager"],
  IT: ["IT Director", "IT Manager", "CTO", "Infrastructure Manager", "Procurement Manager"],
};

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

export const CAMPAIGN_STATUS_LABEL: Record<CampaignStatus, string> = {
  DRAFT: "Draft",
  READY: "Ready",
  RUNNING: "Running",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

export const ODOO_STATUS_LABEL: Record<OdooStatus, string> = {
  NOT_CHECKED: "Not checked",
  AVAILABLE: "Available",
  EXISTING_CONTACT: "Existing Odoo contact",
  EXISTING_LEAD: "Existing CRM lead",
  EXISTING_OPPORTUNITY: "Open opportunity",
  CUSTOMER: "Existing customer",
  LOST_OPPORTUNITY: "Lost opportunity",
  PREVIOUSLY_CONTACTED: "Previously contacted",
  CHECK_FAILED: "Check failed",
};

/** Filter order for CRM status selects. */
export const ODOO_STATUSES: OdooStatus[] = [
  "AVAILABLE",
  "CUSTOMER",
  "EXISTING_OPPORTUNITY",
  "EXISTING_LEAD",
  "LOST_OPPORTUNITY",
  "EXISTING_CONTACT",
  "NOT_CHECKED",
];

export const SOURCE_LABEL: Record<CompanySource, string> = {
  MANUAL: "Manual",
  ODOO_IMPORT: "Odoo import",
  DEMO: "Demo data",
  DISCOVERY: "Discovery",
};

export const IMPORT_TYPE_LABEL: Record<ImportType, string> = {
  ODOO_CRM: "CRM leads & opportunities",
  ODOO_CONTACTS: "Contacts & companies",
};

export const ACTIVITY_LABEL: Record<ActivityType, string> = {
  COMPANY_CREATED: "Company created",
  CAMPAIGN_CREATED: "Campaign created",
  COMPANY_ADDED_TO_CAMPAIGN: "Added to campaign",
  CONTACT_ADDED: "Contact added",
  NOTE_ADDED: "Note",
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

export const COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5000+"];

/** Campaign size presets map to the stored min/max employee counts. */
export const CAMPAIGN_SIZE_RANGES: { label: string; min: number | null; max: number | null }[] = [
  { label: "Any size", min: null, max: null },
  { label: "1-10 employees", min: 1, max: 10 },
  { label: "11-50 employees", min: 11, max: 50 },
  { label: "51-200 employees", min: 51, max: 200 },
  { label: "201-500 employees", min: 201, max: 500 },
  { label: "501-1000 employees", min: 501, max: 1000 },
  { label: "1000+ employees", min: 1001, max: null },
];

export const TARGET_COUNTS = [20, 50, 100, 250, 500];

export const SENIORITIES = ["Owner", "C-Level", "VP", "Director", "Manager", "Senior", "Entry", "Other"];

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

export const SOURCE_NAME: Record<string, string> = {
  OVERTURE: "Overture Maps",
  OSM: "OpenStreetMap",
  LEADFINDER: "LeadFinder",
};
