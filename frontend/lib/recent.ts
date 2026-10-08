import type { Company } from "@/types";

/** Recently opened companies, kept in this browser only (a personal shortcut, not shared data). */
export type RecentCompany = Pick<Company, "id" | "name" | "domain" | "city" | "country" | "odoo_status">;

const KEY = "lf.recent.companies";
const MAX = 6;

export function recentCompanies(): RecentCompany[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]") as RecentCompany[];
  } catch {
    return [];
  }
}

export function rememberCompany(c: RecentCompany) {
  try {
    const entry: RecentCompany = { id: c.id, name: c.name, domain: c.domain, city: c.city, country: c.country, odoo_status: c.odoo_status };
    const next = [entry, ...recentCompanies().filter((r) => r.id !== c.id)].slice(0, MAX);
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: nothing is remembered */
  }
}
