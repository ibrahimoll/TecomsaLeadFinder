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
  | "NOTE_ADDED";

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
  view_crm: boolean;
  run_imports: boolean;
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
  description: string | null;
  source: CompanySource;
  source_label: string;
  odoo_status: OdooStatus;
  crm_status_reason: string | null;
  crm_checked_at: string | null;
  is_protected: boolean;
  salesperson: SalespersonBrief | null;
  creator: UserBrief | null;
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

export interface ImportPreview {
  run: ImportRun;
  type_label: string;
  fields: { key: string; label: string; required: boolean; important: boolean; column: string | null }[];
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

export type IntegrationState = "CONFIGURED" | "NOT_CONFIGURED" | "DISABLED" | "ERROR";

export interface SystemStatus {
  version: string;
  environment: string;
  managers_can_import: boolean;
  last_odoo_import_at: string | null;
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
  | "DUPLICATE";
export type DiscoveryGroup = "available" | "known" | "protected" | "duplicate" | "all";

export interface DiscoveryOptions {
  countries: { code: string; name: string }[];
  areas: Record<string, { key: string; label: string; kind: "city" | "governorate" }[]>;
  industries: { key: string; label: string }[];
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
  duplicate_count: number;
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
  duplicate_of_id: number | null;
  company: { id: number; name: string; odoo_status: OdooStatus } | null;
}

export interface DiscoveryResultsPage extends Page<DiscoveryResult> {
  counts: Record<DiscoveryGroup, number>;
}

export interface CompanySourceInfo {
  source: string;
  source_label: string;
  external_id: string;
  category: string | null;
  first_seen_at: string;
  last_seen_at: string;
  first_seen_run_id: number | null;
}
