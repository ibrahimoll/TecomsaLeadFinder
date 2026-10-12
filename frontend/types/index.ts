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
  /** Managers / admins: licensed directory imports (/imports). */
  run_imports?: boolean;
  /** V1 only (parked legacy pages); the V2 backend no longer sends it. */
  view_crm?: boolean;
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

export interface AuditLog {
  id: number;
  user: UserBrief | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export type IntegrationState = "CONFIGURED" | "ACTIVE" | "NOT_CONFIGURED" | "DISABLED" | "ERROR";

export interface SystemStatus {
  version: string;
  environment: string;
  integrations: { name: string; status: IntegrationState; detail: string }[];
}
export type DiscoveryConfidence = "HIGH" | "MEDIUM" | "LOW";

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
export type Confidence = "HIGH" | "MEDIUM" | "LOW";

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
