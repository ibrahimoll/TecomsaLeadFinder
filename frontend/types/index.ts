export type UserRole = "ADMIN" | "SALES_MANAGER" | "SALES_AGENT";
export type Division = "FRINZO" | "ODOO" | "IT";
export type CampaignStatus = "DRAFT" | "READY" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
export type CampaignCompanyStatus = "ADDED" | "REVIEW" | "REMOVED";
export type OdooStatus =
  | "NOT_CHECKED"
  | "AVAILABLE"
  | "EXISTING_CONTACT"
  | "EXISTING_LEAD"
  | "EXISTING_OPPORTUNITY"
  | "CUSTOMER"
  | "LOST_OPPORTUNITY"
  | "PREVIOUSLY_CONTACTED"
  | "CHECK_FAILED";
export type CompanySource = "MANUAL" | "ODOO_IMPORT" | "DEMO" | "DISCOVERY";
export type ImportType = "ODOO_CRM" | "ODOO_CONTACTS";
export type ImportStatus = "PREVIEW" | "COMPLETED" | "FAILED" | "CANCELLED";
export type ActivityType =
  | "COMPANY_CREATED"
  | "CAMPAIGN_CREATED"
  | "COMPANY_ADDED_TO_CAMPAIGN"
  | "CONTACT_ADDED"
  | "NOTE_ADDED"
  | "OPPORTUNITY_CREATED"
  | "CONTACTED"
  | "ACTIVITY_PLANNED"
  | "STATUS_CHANGED"
  | "LEAD_REASSIGNED";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface UserBrief {
  id: number;
  name: string;
}

export interface User {
  id: number;
  name: string;
  email: string;
  role: UserRole;
  odoo_user_id: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
}

export interface Capabilities {
  manage_users: boolean;
  /** V1 only (parked legacy pages); the V2 backend no longer sends these. */
  view_crm?: boolean;
  run_imports?: boolean;
}

export interface Me extends User {
  capabilities: Capabilities;
}

export interface SalespersonBrief {
  id: number;
  name: string;
}

export interface Company {
  id: number;
  name: string;
  normalized_name: string;
  website: string | null;
  domain: string | null;
  country: string | null;
  city: string | null;
  address: string | null;
  industry: string | null;
  main_phone: string | null;
  main_phone_normalized: string | null;
  main_email: string | null;
  company_size: string | null;
  /** How well the discovery sources support it being a real, relevant business. Not its size. */
  discovery_confidence: DiscoveryConfidence | null;
  discovery_evidence: { confidence: DiscoveryConfidence; reasons: string[]; concerns: string[]; signals: string[]; run_id: number } | null;
  description: string | null;
  source: CompanySource;
  source_label: string;
  odoo_status: OdooStatus;
  crm_status_reason: string | null;
  crm_checked_at: string | null;
  is_protected: boolean;
  salesperson: SalespersonBrief | null;
  creator: UserBrief | null;
  owner: UserBrief | null; // owner of a discovered candidate (shown to managers/admins and the owner)
  created_at: string;
  updated_at: string;
}

export interface CompanyBrief {
  id: number;
  name: string;
  domain: string | null;
  city: string | null;
  country: string | null;
  source_label: string;
  odoo_status: OdooStatus;
}

export interface DuplicateCandidate {
  company: CompanyBrief;
  score: number;
  reason: string;
}

export interface CrmLead {
  id: number;
  odoo_lead_id: number | null;
  odoo_external_id: string | null;
  opportunity_name: string;
  company_name: string | null;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  mobile: string | null;
  salesperson_name: string | null;
  salesperson: SalespersonBrief | null;
  sales_team: string | null;
  stage: string | null;
  lead_type: "LEAD" | "OPPORTUNITY";
  expected_revenue: string | null;
  probability: string | null;
  active: boolean;
  is_won: boolean;
  is_lost: boolean;
  is_open: boolean;
  lost_reason: string | null;
  created_date: string | null;
  updated_date: string | null;
  last_activity: string | null;
  company: { id: number; name: string } | null;
  imported_at: string;
}

export interface OdooContact {
  id: number;
  odoo_contact_id: number | null;
  odoo_external_id: string | null;
  contact_name: string;
  is_company: boolean;
  parent_company: string | null;
  job_position: string | null;
  website: string | null;
  email: string | null;
  phone: string | null;
  mobile: string | null;
  city: string | null;
  country: string | null;
  is_customer: boolean;
  salesperson_name: string | null;
  salesperson: SalespersonBrief | null;
  company: { id: number; name: string } | null;
  imported_at: string;
}

export interface ImportRun {
  id: number;
  import_type: ImportType;
  status: ImportStatus;
  original_filename: string;
  file_type: string;
  file_size: number;
  row_count: number;
  valid_count: number;
  warning_count: number;
  duplicate_count: number;
  inserted_count: number;
  updated_count: number;
  skipped_count: number;
  error_count: number;
  companies_created: number;
  companies_linked: number;
  column_mapping: Record<string, string>;
  detected_columns: string[];
  issues: { row: number; level: "error" | "warning" | "duplicate"; message: string }[];
  failure_reason: string | null;
  creator: UserBrief | null;
  created_at: string;
  completed_at: string | null;
}

export interface ImportStructure {
  table: string;
  sheet: string;
  header_rows: number[];
  first_row: number | null;
  last_row: number | null;
  data_rows: number;
  skipped_rows: { row: number; reason: string }[];
  skipped_count: number;
  fields_recognized: number;
  identity_confidence: string;
  choice_needed: boolean;
  sheets: { sheet: string; status: string; tables?: number }[];
  tables: { id: string; sheet: string; header_rows: number[]; first_row: number; last_row: number; data_rows: number; usable: boolean; fields: string[]; chosen: boolean }[];
  columns: { column: string; header: string | null; label: string; concept: string; concept_label: string; confidence: string; samples: string[]; imported?: boolean }[];
}

export interface ImportPreview {
  run: ImportRun;
  type_label: string;
  fields: { key: string; label: string; required: boolean; important: boolean; column: string | null; confidence?: string | null }[];
  /** How LeadFinder read the file (sheets, tables, header / data rows, column meanings). */
  structure?: ImportStructure | null;
  unmapped_columns: string[];
  missing_important: string[];
  new_records: number;
  existing_records: number;
  companies_matched: number;
  companies_new: number;
  sample_rows: {
    row: number;
    status: "new" | "update" | "warning" | "error" | "duplicate";
    /** Contacts: company, contact, position, phone, email, country, city. CRM: opportunity, company, contact, salesperson, stage. */
    values: Record<string, string | number | boolean | null>;
    messages: string[];
    company_match: { id: number; name: string; reason: string } | null;
  }[];
  previous_import: { id: number; completed_at: string } | null;
}

export interface ImportDeleteResult {
  id: number;
  with_data: boolean;
  removed: { crm_records: number; odoo_contacts: number; companies: number; salespeople: number };
  kept: { records: number; companies: number };
}

export interface SalespersonRow {
  salesperson: {
    id: number;
    name: string;
    email: string | null;
    odoo_user_id: number | null;
    active: boolean;
    user: UserBrief | null;
    created_at: string;
  };
  crm_records: number;
  open_records: number;
  odoo_contacts: number;
  companies: number;
}

export interface Contact {
  id: number;
  company_id: number;
  first_name: string;
  last_name: string | null;
  full_name: string;
  job_title: string | null;
  department: string | null;
  seniority: string | null;
  business_email: string | null;
  business_phone: string | null;
  linkedin_url: string | null;
  source: string;
  created_at: string;
}

export interface OdooMatch {
  match_status: OdooStatus;
  odoo_partner_id: number | null;
  odoo_lead_id: number | null;
  match_confidence: string | null;
  match_reason: string | null;
  checked_at: string | null;
  created_at: string;
}

export interface CompanyCampaignLink {
  campaign_id: number;
  campaign_name: string;
  tecomsa_division: Division;
  campaign_status: CampaignStatus;
  status: CampaignCompanyStatus;
  qualification_status: string;
  added_at: string;
}

export interface CompanyDetail extends Company {
  contacts: Contact[];
  campaigns: CompanyCampaignLink[];
  odoo_match: OdooMatch | null;
  relationship: {
    crm_records: CrmLead[];
    odoo_contacts: OdooContact[];
    last_interaction: string | null;
  };
  possible_duplicates: DuplicateCandidate[];
  sources: CompanySourceInfo[];
  /** Physical locations (branches, factories, shops); duplicate listings of a place are folded in. */
  locations: CompanyLocation[];
  lusha_credits_used: number;
  can_edit: boolean;
}

export interface Campaign {
  id: number;
  name: string;
  tecomsa_division: Division;
  country: string;
  region: string | null;
  city: string | null;
  industry: string | null;
  company_size_min: number | null;
  company_size_max: number | null;
  target_roles: string[];
  target_company_count: number;
  max_lusha_credit_budget: number | null;
  additional_instructions: string | null;
  status: CampaignStatus;
  creator: UserBrief;
  company_count: number;
  created_at: string;
  updated_at: string;
}

export interface CampaignCompany {
  id: number;
  campaign_id: number;
  company: {
    id: number;
    name: string;
    country: string | null;
    industry: string | null;
    domain: string | null;
    odoo_status: OdooStatus;
  };
  status: CampaignCompanyStatus;
  qualification_status: string;
  created_at: string;
}

export interface CampaignDetail extends Campaign {
  companies: CampaignCompany[];
  lusha_credits_used: number;
  can_edit: boolean;
}

export interface Activity {
  id: number;
  activity_type: ActivityType;
  notes: string | null;
  user: UserBrief | null;
  company: { id: number; name: string } | null;
  campaign: { id: number; name: string } | null;
  contact: { id: number; full_name: string } | null;
  created_at: string;
  kind?: SalesActivityKind | null;
  due_date?: string | null;
  done_at?: string | null;
}

export interface AuditLog {
  id: number;
  user: UserBrief | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface DashboardSummary {
  sales?: SalesCounts;
  total_companies: number;
  protected_companies: number;
  available_companies: number;
  unchecked_companies: number;
  odoo_crm_records: number;
  odoo_open_records: number;
  odoo_contacts: number;
  my_campaigns: number;
  draft_campaigns: number;
  lusha_credits_used: number;
  latest_imports: {
    id: number;
    import_type: ImportType;
    status: ImportStatus;
    original_filename: string;
    row_count: number;
    inserted_count: number;
    updated_count: number;
    created_at: string;
  }[];
  recent_companies: Company[];
  recent_campaigns: {
    id: number;
    name: string;
    tecomsa_division: Division;
    status: CampaignStatus;
    target_company_count: number;
    created_at: string;
  }[];
  recent_activity: Activity[];
}

export type IntegrationState = "CONFIGURED" | "ACTIVE" | "NOT_CONFIGURED" | "DISABLED" | "ERROR";

export interface SystemStatus {
  version: string;
  environment: string;
  integrations: { name: string; status: IntegrationState; detail: string }[];
}

export type DiscoveryStatus = "QUEUED" | "SEARCHING" | "PROCESSING" | "COMPLETED" | "PARTIAL" | "FAILED";
export type DiscoveryState =
  | "AVAILABLE"
  | "EXISTING_LEADFINDER"
  | "EXISTING_ODOO_CONTACT"
  | "EXISTING_CRM_LEAD"
  | "OPEN_OPPORTUNITY"
  | "CUSTOMER"
  | "LOST_OPPORTUNITY"
  | "PROTECTED"
  | "POSSIBLE_ODOO_MATCH"
  | "DUPLICATE"
  | "MERGED_BRANCH"
  | "CLOSED"
  | "WRONG_INDUSTRY"
  | "LOW_CONFIDENCE"
  /** Another salesperson's private candidate. Only managers and admins ever receive these rows. */
  | "RESERVED";
export type DiscoveryConfidence = "HIGH" | "MEDIUM" | "LOW";
export type DiscoveryGroup = "available" | "low" | "known" | "protected" | "possible" | "duplicate" | "rejected" | "all";

export interface DiscoveryOptions {
  countries: { code: string; name: string }[];
  areas: Record<string, { key: string; label: string; kind: "city" | "governorate" }[]>;
  /** `group` is "Featured" for LeadFinder's tuned industries, else the Overture top-level category. */
  industries: { key: string; label: string; group: string }[];
  counts: number[];
  sources: { key: string; label: string }[];
}

export interface DiscoveryRun {
  id: number;
  country: string;
  city: string | null;
  industry: string | null;
  custom_query: string | null;
  query_label: string;
  requested_count: number;
  sources: string[];
  source_version: string | null;
  status: DiscoveryStatus;
  progress: { key: string; label: string; detail: string | null; state: "active" | "done" | "failed" }[];
  started_at: string | null;
  finished_at: string | null;
  source_match_count: number;
  raw_results_count: number;
  /** The same place listed again. */
  duplicate_count: number;
  /** Other locations folded into a company. */
  branch_count: number;
  /** Unique companies after consolidating branches and duplicates. */
  company_count: number;
  existing_company_count: number;
  odoo_protected_count: number;
  new_company_count: number;
  error_count: number;
  errors: string[];
  summary: string | null;
  creator: UserBrief | null;
  created_at: string;
}

export interface DiscoveryResult {
  id: number;
  position: number;
  source: string;
  external_id: string | null;
  name: string;
  category: string | null;
  address: string | null;
  city: string | null;
  country: string | null;
  phone: string | null;
  website: string | null;
  email: string | null;
  latitude: number | null;
  longitude: number | null;
  state: DiscoveryState;
  reason: string | null;
  match_reason: string | null;
  confidence: DiscoveryConfidence | null;
  evidence: string[];
  concerns: string[];
  signals: string[];
  /** On a company's row: the distinct locations this search found. */
  locations: { name: string; city: string | null; address: string | null; source: string }[];
  sources: string[];
  duplicate_of_id: number | null;
  /** `owner` (who found it) is only sent to managers and admins. */
  company: { id: number; name: string; odoo_status: OdooStatus; location_count: number | null; owner: UserBrief | null } | null;
}

export interface DiscoveryResultsPage extends Page<DiscoveryResult> {
  counts: Record<DiscoveryGroup, number>;
  state_counts: Partial<Record<DiscoveryState, number>>;
  confidence_counts: Partial<Record<DiscoveryConfidence, number>>;
  cities: string[];
}

export interface CompanySourceInfo {
  source: string;
  source_label: string;
  external_id: string;
  category: string | null;
  name: string | null;
  city: string | null;
  address: string | null;
  same_place_as_external_id: string | null;
  first_seen_at: string;
  last_seen_at: string;
  first_seen_run_id: number | null;
}

export interface CompanyLocation {
  name: string | null;
  city: string | null;
  address: string | null;
  phone: string | null;
  latitude: number | null;
  longitude: number | null;
  sources: string[];
  first_seen_at: string;
}

// ---- Phase 2: research & qualification ----------------------------------------------------

export type WebsiteStatus =
  | "ACTIVE" | "REDIRECTED" | "PLACEHOLDER" | "PARKED" | "FOR_SALE" | "EMPTY" | "UNREACHABLE" | "BLOCKED"
  | "NO_WEBSITE" | "VALIDATION_FAILED";
export type ResearchStatus =
  | "QUEUED" | "RESEARCHING" | "RESEARCHED" | "COMPLETED" | "RESEARCH_FAILED" | "QUALIFICATION_FAILED";
export type LeadQualification = "QUALIFIED" | "NEEDS_REVIEW" | "LOW_PRIORITY" | "INSUFFICIENT_EVIDENCE";
export type ScaleSignal = "STRONG" | "MODERATE" | "LIMITED" | "UNKNOWN";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";

export interface EvidenceFact {
  id: string;
  signal: string;
  label: string;
  value: string;
  kind: "EXPLICIT_FACT" | "LEADFINDER_INFERENCE";
  evidence: string;
  source_url: string | null;
  source: string;
  from_run?: number;
}

export interface Qualification {
  id: number;
  provider: string;
  model: string | null;
  qualification_version: string;
  rubric_version: string;
  reused_from_id: number | null;
  odoo_fit_score: number;
  odoo_confidence: Confidence;
  odoo_reasons: string[];
  recommended_modules: { module: string; reason: string; source_url: string | null }[];
  frinzo_fit_score: number;
  frinzo_confidence: Confidence;
  frinzo_reasons: string[];
  frinzo_use_cases: { use_case: string; reason: string; source_url: string | null }[];
  scale_signal: ScaleSignal;
  scale_reasons: string[];
  qualification_status: LeadQualification;
  priority: Confidence;
  status_reason: string | null;
  summary: string | null;
  rejected_evidence: { signal: string; evidence: string; source_url: string | null; reason: string }[];
  generated_at: string;
}

export interface ResearchRun {
  id: number;
  company_id: number;
  status: ResearchStatus;
  force: boolean;
  website_url: string | null;
  final_url: string | null;
  website_status: WebsiteStatus | null;
  website_detail: string | null;
  website_risk: "STRONG" | "MODERATE" | null;
  http_status: number | null;
  https_ok: boolean | null;
  validated_at: string | null;
  crawl_started_at: string | null;
  crawl_finished_at: string | null;
  pages_crawled: number;
  failed_stage: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  initiator: UserBrief | null;
  qualification_status: LeadQualification | null;
  reused_from_run_id: number | null;
  contact_source: "FREE" | "APOLLO" | "LUSHA" | null;
  dm_target: string | null;
  dm_custom_title: string | null;
  want_email: boolean;
  want_phone: boolean;
  contact_status: "PENDING" | "RUNNING" | "SKIPPED" | "COMPLETED" | "PARTIAL" | "FAILED" | null;
  contact_summary: { person_id?: number | null; email?: string; phone?: string; source?: string; messages?: string[] };
  decision_maker_run_id: number | null;
}

export interface ResearchRunDetail extends ResearchRun {
  pages: { url: string; title?: string; kind?: string; skipped?: string; carried_from_run?: number; carried_pages?: number }[];
  evidence: EvidenceFact[];
  business_signals: { signal: string; label: string; status: "CONFIRMED" | "UNKNOWN"; value: string | null; kind: string | null; source_url: string | null }[];
  qualification: Qualification | null;
}

export interface ResearchStartResult {
  runs: ResearchRun[];
  skipped: { company_id: number; name: string; reason: string }[];
}

export interface QualifiedLead {
  company_id: number;
  name: string;
  industry: string | null;
  city: string | null;
  owner: UserBrief | null;
  run_id: number;
  researched_at: string | null;
  website_status: WebsiteStatus | null;
  final_url: string | null;
  scale_signal: ScaleSignal;
  odoo_fit_score: number;
  odoo_confidence: Confidence;
  frinzo_fit_score: number;
  frinzo_confidence: Confidence;
  qualification_status: LeadQualification;
  priority: Confidence;
  status_reason: string | null;
  provider: string;
  model: string | null;
  decision_makers?: number;
  primary_contact?: { id: number; name: string; title: string | null; score: number; label: string; email_status: string; phone_status: string } | null;
  needs_review?: boolean;
  sales?: SalesSummary | null;
}

// ---- Phase 3: decision-makers & contact enrichment ---------------------------------------------

export type SolutionKey = "ODOO" | "FRINZO";
export type RoleRelevance = "PRIMARY" | "SECONDARY" | "ADJACENT" | "LOW";
export type PersonConfidence = "HIGH" | "MEDIUM" | "LOW" | "UNRELIABLE";

export interface PersonAssessment {
  relevance: RoleRelevance;
  relevance_why: string;
  score: number;
  label: PersonConfidence;
  breakdown: { company_match: number; role_relevance: number; seniority: number; corroboration: number; freshness: number };
  corroboration_why: string;
  freshness_why: string;
  role: string;
  rank?: number;
  why?: string;
}

export interface PersonSource {
  id: number;
  provider: "WEBSITE" | "APOLLO" | "LUSHA";
  source_url: string | null;
  observed_name: string;
  observed_title: string | null;
  observed_company: string | null;
  observed_domain: string | null;
  employment_status: string;
  provider_updated_at: string | null;
  excerpt: string | null;
  fetched_at: string;
  run_id: number | null;
}

export interface DecisionMaker {
  id: number;
  company_id: number;
  first_name: string;
  last_name: string | null;
  last_name_obfuscated: string | null;
  full_name: string;
  title: string | null;
  role_family: string;
  department: string | null;
  seniority: string;
  employment_status: "CURRENT" | "FORMER" | "UNKNOWN";
  needs_review: boolean;
  review_reason: string | null;
  linkedin_url: string | null;
  location: string | null;
  work_email: string | null;
  email_status: "NOT_SEARCHED" | "AVAILABLE" | "VERIFIED" | "UNVERIFIED" | "NOT_FOUND";
  email_provider: string | null;
  email_detail: Record<string, unknown>;
  phone: string | null;
  phone_status: "NOT_SEARCHED" | "PENDING" | "AVAILABLE" | "NOT_FOUND";
  phone_provider: string | null;
  phone_type: string | null;
  phone_dnc: boolean | null;
  assessment: Partial<Record<SolutionKey, PersonAssessment>>;
  best_score: number;
  ranks: string[];
  owner: UserBrief | null;
  sources: PersonSource[];
  updated_at: string;
}

export interface DecisionMakerRun {
  id: number;
  company_id: number;
  status: "QUEUED" | "SEARCHING" | "FOUND" | "PARTIAL" | "NO_MATCH" | "NEEDS_REVIEW" | "FAILED";
  solutions: SolutionKey[];
  target_roles: { titles?: string[]; role_query?: string | null; directory?: boolean } & Partial<Record<SolutionKey, { family: string; label: string; relevance: RoleRelevance; why: string }[]>>;
  providers: { provider: string; status: string; people: number; error?: string; pages?: number }[];
  override: boolean;
  override_reason: string | null;
  people_found: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  created_at: string;
  initiator: UserBrief | null;
}

/** How a person appears in the company's people directory (no Odoo / Frinzo dependency). */
export interface PersonDirectory {
  department: string;
  department_label: string;
  employment: "CURRENT" | "FORMER" | "UNKNOWN";
  confidence: number;
  confidence_label: "HIGH" | "MEDIUM" | "LOW" | "UNRELIABLE";
  breakdown: { company_match: number; employment: number; sources: number; seniority: number; freshness: number };
  sources: string[];
  relevant_for: SolutionKey[];
  section: "CURRENT" | "REVIEW" | "FORMER";
  section_reason: string | null;
  email_state: "NOT_SEARCHED" | "PUBLIC" | "AVAILABLE" | "VERIFIED" | "NOT_FOUND";
  phone_state: "NOT_SEARCHED" | "PENDING" | "AVAILABLE" | "NOT_FOUND";
}

export interface CompanyPeople {
  people: (DecisionMaker & { directory: PersonDirectory })[];
  auto_search: boolean;
  departments: { key: string; label: string; count: number }[];
  runs: DecisionMakerRun[];
  owner_id: number | null;
  owners: UserBrief[];
  eligible: boolean;
  qualification_status: LeadQualification | null;
}

export interface RevealOutcome {
  status: string;
  message: string | null;
  request_id: number | null;
  person: DecisionMaker;
}

export interface ProviderStatus {
  apollo: { status: string; used: number; limit: number; phone_webhook: boolean };
  lusha: { status: string; used: number; limit: number };
  paid_enrichment_enabled: boolean;
  bulk_paid_enrichment_enabled: boolean;
  batch_limit: number;
  costs: { action: string; provider: string; field: string; credits: number; note: string }[];
  note: string;
}

// ---- Phase 4: sales workflow & Odoo CRM handoff ------------------------------------------------

export type LeadStatus = "NEW" | "READY" | "CONTACTED" | "FOLLOW_UP" | "MEETING" | "PROPOSAL" | "WON" | "LOST" | "ON_HOLD";
export type SyncStatus = "NOT_SYNCED" | "SYNCING" | "SYNCED" | "FAILED" | "NEEDS_REVIEW";
export type SalesSolution = "ODOO" | "FRINZO" | "BOTH";
export type SalesActivityKind = "CALL" | "EMAIL" | "WHATSAPP" | "LINKEDIN" | "MEETING" | "FOLLOW_UP" | "DEMO" | "PROPOSAL" | "OTHER";

export interface NextActivity {
  id: number;
  kind: SalesActivityKind | null;
  due_date: string | null;
  note: string | null;
  done_at: string | null;
  overdue: boolean;
  odoo_synced: boolean;
}

export interface OdooReview {
  kind: "EXISTING_OPPORTUNITY" | "POSSIBLE_OPPORTUNITY" | "POSSIBLE_PARTNER";
  message: string;
  can_create: boolean;
  candidates: { id: number | null; name: string | null; stage?: string | null; salesperson?: string | null; url?: string | null; city?: string | null; website?: string | null; phone?: string | null }[];
}

/** Full view for whoever works the lead; colleagues get `limited: true` (an Odoo opportunity exists). */
export interface Opportunity {
  company_id: number;
  limited: boolean;
  sync_status: SyncStatus;
  odoo_stage: string | null;
  odoo_state: "open" | "won" | "lost" | "missing" | null;
  odoo_lead_id: number | null;
  title: string | null;
  id?: number;
  lead_status?: LeadStatus;
  owner?: UserBrief | null;
  solution?: SalesSolution | null;
  expected_revenue?: string | null;
  priority?: number | null;
  notes?: string | null;
  approval_reason?: string | null;
  primary_contact?: { id: number; name: string; title: string | null; email: string | null; phone: string | null } | null;
  sync_error?: string | null;
  review?: OdooReview | null;
  sync_attempts?: number;
  odoo_url?: string | null;
  synced_at?: string | null;
  last_sync_at?: string | null;
  odoo_salesperson?: string | null;
  odoo_next_activity?: { date: string; summary: string | null; type: string | null } | null;
  next_activity?: NextActivity | null;
}

export interface OpportunityResult {
  outcome: "CREATED" | "RECONCILED" | "ALREADY_CREATED" | "IN_PROGRESS" | "EXISTING" | "NEEDS_REVIEW" | "FAILED" | "REFRESHED" | "CACHED" | "REASSIGNED" | "UPDATED" | "UNCHANGED";
  warnings: string[];
  opportunity: Opportunity;
}

export interface OpportunityDraft {
  company_id: number;
  title: string;
  solution: SalesSolution;
  owner_id: number;
  owners: { id: number; name: string }[];
  people: { id: number; name: string; title: string | null; email: string | null; phone: string | null; score: number; recommended: boolean; needs_review: boolean }[];
  decision_maker_id: number | null;
  priority: number;
  notes: string;
  qualification_status: string | null;
  needs_approval: string | null;
  can_approve: boolean;
  existing: { message: string; odoo_lead_id: number | null } | null;
  can_create: boolean;
  odoo_connected: boolean;
}

export interface SalesSummary {
  lead_status: LeadStatus | null;
  sync_status: SyncStatus;
  odoo_stage: string | null;
  odoo_state: string | null;
  next_activity: NextActivity | null;
}

export interface MyLead {
  company_id: number;
  name: string;
  city: string | null;
  lead_status: LeadStatus;
  sync_status: SyncStatus;
  title: string | null;
  odoo_stage: string | null;
  odoo_state: string | null;
  owner: UserBrief | null;
  next_activity: NextActivity | null;
  due: boolean;
}

export interface SalesCounts {
  ready: number;
  due: number;
  overdue: number;
  meetings: number;
  proposals: number;
  opportunities: number;
  no_next_activity: number;
  won: number;
  lost: number;
}
