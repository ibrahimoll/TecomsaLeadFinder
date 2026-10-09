import type { Tone } from "@/components/ui";
import type { CompanyStatus } from "@/types/v2";

export const COMPANY_STATUS: Record<CompanyStatus, { label: string; tone: Tone }> = {
  new: { label: "New", tone: "neutral" },
  qualified: { label: "Qualified", tone: "info" },
  contacted: { label: "Contacted", tone: "info" },
  follow_up: { label: "Follow-up", tone: "warning" },
  meeting_scheduled: { label: "Meeting scheduled", tone: "accent" },
  opportunity: { label: "Opportunity", tone: "accent" },
  working_odoo: { label: "Working · Odoo", tone: "success" },
  working_frinzo: { label: "Working · Frinzo", tone: "success" },
  working_it: { label: "Working · IT", tone: "success" },
  not_interested: { label: "Not interested", tone: "neutral" },
  do_not_contact: { label: "Do not contact", tone: "danger" },
  archived: { label: "Archived", tone: "neutral" },
};

export const COMPANY_STATUSES = Object.keys(COMPANY_STATUS) as CompanyStatus[];

/** LeadFinder's normalized industries (backend: services/discovery/industries.py). Free text works too. */
export const INDUSTRIES = [
  "Food Manufacturing",
  "Food & Beverage",
  "Manufacturing",
  "Retail",
  "Distribution",
  "Wholesale",
  "Healthcare",
  "Hospitality",
  "Construction",
  "Real Estate",
  "Professional Services",
  "Automotive",
  "Education",
  "Technology",
  "Telecom",
  "Logistics",
  "Financial Services",
  "Insurance",
  "Pharmaceutical",
  "Agriculture",
  "Banking",
  "Hotels",
  "Restaurants & Cafés",
  "Hospitals & Clinics",
  "Laboratories",
  "Pharmacies",
  "Supermarkets & Grocery",
  "Fashion & Apparel",
  "Electronics & Appliances",
  "Jewelry",
  "Beauty & Cosmetics",
  "Furniture",
  "Chemicals & Plastics",
  "Textiles",
  "Printing & Packaging",
  "Energy & Utilities",
  "Engineering",
  "Media & Advertising",
  "Legal Services",
  "Accounting & Consulting",
  "Travel & Tourism",
  "Import & Export",
  "Security Services",
  "Cleaning & Waste Management",
  "Events & Venues",
  "Fitness & Sports",
  "NGOs & Charities",
];

export const CONFIDENCE: Record<"low" | "medium" | "high", { label: string; tone: Tone }> = {
  high: { label: "High", tone: "success" },
  medium: { label: "Medium", tone: "info" },
  low: { label: "Low", tone: "warning" },
};

/** "Beirut, Mount Lebanon, Lebanon" from whatever parts are known. */
export function place(...parts: (string | null | undefined)[]): string {
  return [...new Set(parts.filter(Boolean))].join(", ") || "—";
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  const text = value.replace(/_/g, " ");
  return text.length <= 3 ? text.toUpperCase() : text[0]!.toUpperCase() + text.slice(1);
}
