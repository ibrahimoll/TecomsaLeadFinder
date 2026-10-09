import type { PeopleResearch } from "@/lib/people-research";
export type { PeopleResearch };

/** LeadFinder V2 API types (backend: app/schemas/company.py, app/schemas/lead_search.py). */

export type CompanyStatus =
  | "new"
  | "qualified"
  | "contacted"
  | "follow_up"
  | "meeting_scheduled"
  | "opportunity"
  | "working_odoo"
  | "working_frinzo"
  | "working_it"
  | "not_interested"
  | "do_not_contact"
  | "archived";

export interface Company {
  id: number;
  name: string;
  legal_name: string | null;
  normalized_name: string;
  domain: string | null;
  website: string | null;
  description: string | null;
  industry: string | null;
  sub_industry: string | null;
  company_type: string | null;
  employee_count_estimate: number | null;
  founded_year: number | null;
  headquarters_country: string | null;
  headquarters_region: string | null;
  headquarters_city: string | null;
  primary_phone: string | null;
  primary_email: string | null;
  linkedin_url: string | null;
  instagram_url: string | null;
  facebook_url: string | null;
  youtube_url: string | null;
  tiktok_url: string | null;
  twitter_url: string | null;
  /** A range when only a range is published ("more than 500 employees"). */
  employee_count_min: number | null;
  employee_count_max: number | null;
  status: CompanyStatus;
  status_reason: string | null;
  identity_confidence: "low" | "medium" | "high" | null;
  /** Company research (website enrichment), separate from discovery and from the sales status. */
  enrichment_status: EnrichmentStatus;
  enrichment_message: string | null;
  last_enriched_at: string | null;
  /** 0-100: how sure LeadFinder is that the website is the company's own. */
  website_confidence: number | null;
  /** People discovery, separate from company research. */
  people_status: EnrichmentStatus;
  people_message: string | null;
  people_researched_at: string | null;
  /** People from public sources beyond the company's website (conferences, associations, news, documents). */
  external_people_status: EnrichmentStatus;
  external_people_researched_at: string | null;
  contact_status: EnrichmentStatus;
  last_researched_at: string | null;
  last_verified_at: string | null;
  created_by_user_id: number | null;
  created_at: string;
  updated_at: string;
}

export type EnrichmentStatus = "not_started" | "queued" | "researching" | "partial" | "completed" | "failed" | "timed_out";

export interface CompanyLocation {
  id: number;
  location_type: string | null;
  country: string;
  region: string | null;
  city: string | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  is_headquarters: boolean;
  name: string | null;
  phone: string | null;
  source_id: number | null;
  confidence: number | null;
}

export interface ContactEmail {
  id: number;
  email: string;
  email_type: string | null;
  purpose: string | null;
  status: string;
  is_primary: boolean;
  is_public: boolean;
  confidence: number | null;
  source_id: number | null;
  last_verified_at: string | null;
}

export interface ContactPhone {
  id: number;
  phone: string;
  normalized_phone: string | null;
  phone_type: string | null;
  purpose: string | null;
  status: string;
  is_primary: boolean;
  is_public: boolean;
  confidence: number | null;
  source_id: number | null;
  last_verified_at: string | null;
}

export interface CompanyPerson {
  id: number;
  person: { id: number; full_name: string; first_name: string | null; last_name: string | null; location_country: string | null; location_city: string | null; profile_url: string | null };
  job_title: string;
  normalized_title: string | null;
  department: string | null;
  seniority: string | null;
  is_current: boolean;
  started_at: string | null;
  ended_at: string | null;
  confidence: number | null;
  last_verified_at: string | null;
  primary_source_id: number | null;
  emails: ContactEmail[];
  phones: ContactPhone[];
  /** How to reach the person, strongest first; the label says how sure (Verified / Published / Predicted...). */
  contacts: { kind: string; value: string; label: string; since?: string | null; stale?: boolean }[];
  /** A usable business channel (a predicted address alone is not one). */
  contactable: boolean;
  employment_status: "current" | "former" | "unknown";
  title_rank: number | null;
  /** The department's first decision-maker. */
  is_key: boolean;
  sources: { id: number; name: string | null; url: string | null; page_type: string | null; source_type: string | null; page: number | null }[];
  /** Corrected by hand: research does not change these. */
  corrected_fields: string[] | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

export interface Opportunity {
  id: number;
  solution: "odoo" | "frinzo" | "it";
  fit_level: "unknown" | "low" | "medium" | "high" | null;
  summary: string | null;
  reasoning: unknown;
  signals: unknown;
  recommended_modules_or_services: unknown;
  recommended_person_ids: number[] | null;
  confidence: number | null;
  generated_at: string;
  expires_at: string | null;
}

export interface SourceSummary {
  id: number;
  source_type: string;
  name: string | null;
  url: string | null;
  publisher: string | null;
  retrieved_at: string | null;
  source_quality: number | null;
  evidence_count: number;
  /** Page of the company's own website (about, contact...). */
  page_type: string | null;
  /** The fields this source supports. */
  facts: string[];
}

export type SignalGroup = "activity" | "operations" | "technology" | "hiring" | "news" | "events";

export interface CompanySignal {
  id: number;
  signal_type: string;
  group: SignalGroup;
  signal_value: string | null;
  confidence: number | null;
  source_id: number;
  observed_at: string | null;
  /** Dated business events (the company timeline). */
  event_date?: string | null;
  description?: string | null;
}

export interface CompanyRelationship {
  relation_type: string;
  related_name: string;
  related_company_id: number | null;
  source_id: number;
}

export interface RelatedGroupPerson {
  person_id: number;
  full_name: string;
  job_title: string;
  department: string | null;
  employment_status: string;
  employer_id: number;
  employer_name: string;
  relation_type: string;
}

export interface CompanyOffering {
  id: number;
  kind: "product" | "service" | "category";
  raw_name: string;
  confidence: number | null;
  source_id: number;
}

export interface FieldConflict {
  field: string;
  values: { value: string; confidence: number | null; source: string | null }[];
}

/** A direct-search match: a LeadFinder company, or a public-source candidate (company_id null, pick_index set). */
export interface CompanySearchHit {
  company_id: number | null;
  name: string;
  legal_name: string | null;
  city: string | null;
  country: string | null;
  industry: string | null;
  website: string | null;
  domain: string | null;
  match_type: string | null;
  confidence: "exact" | "strong" | "possible" | "weak" | null;
  detail: string | null;
  source: string | null;
  pick_index: number | null;
}

export interface CompanyLookup {
  lookup_id: number | null;
  query: string;
  status: "found" | "created" | "ambiguous" | "not_found" | "timed_out" | "failed";
  company: CompanySearchHit | null;
  candidates: CompanySearchHit[];
  match_type: string | null;
  confidence: string | null;
  external_used: boolean;
  created: boolean;
  parsed: Record<string, unknown>;
  resolved_from: string | null;
  failure_reason: string | null;
  duration_ms: number | null;
}

export interface CompanyDetail {
  company: Company;
  people_research: PeopleResearch | null;
  locations: CompanyLocation[];
  people: CompanyPerson[];
  emails: ContactEmail[];
  phones: ContactPhone[];
  opportunities: Opportunity[];
  sources: SourceSummary[];
  signals: CompanySignal[];
  /** Parent / subsidiary... (separate entities, never merged). */
  relationships?: CompanyRelationship[];
  /** People of the parent / group: employed by the group, not by this company. */
  related_group_people?: RelatedGroupPerson[];
  offerings: CompanyOffering[];
  /** Fields whose sources disagree; the strongest value is the one shown. */
  conflicts: FieldConflict[];
  /** Factual summary built from the stored fields only. */
  overview: string | null;
}

export type Solution = "any" | "odoo" | "frinzo" | "it";
export type LeadSearchStatus = "pending" | "researching" | "completed" | "partial" | "failed";

export interface LeadSearch {
  id: number;
  user_id: number;
  country: string;
  region: string | null;
  city: string | null;
  industry: string | null;
  solution: Solution;
  requested_count: number;
  /** Discovery: final as soon as the companies are found. */
  status: LeadSearchStatus;
  /** Research of the companies found, which continues after discovery. */
  enrichment_status: "running" | "completed" | null;
  /** Matching companies already in LeadFinder (not returned: Find Leads finds new ones). */
  already_known?: number | null;
  companies_found: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  connectors_total: number;
  connectors_completed: number;
  /** One sentence for the user, e.g. why a search is partial. */
  message: string | null;
  /** Per-source counts and errors: managers and admins only. */
  diagnostics: { connectors?: Record<string, Record<string, unknown>> } | null;
}

export interface LeadSearchResult {
  rank: number | null;
  relevance_score: number | null;
  /** Added to LeadFinder by this search (false: an already known company). */
  is_new: boolean;
  source_count: number;
  company: Company;
}
