export type UserRole = "ADMIN" | "SALES_MANAGER" | "SALES_AGENT";
export type Division = "FRINZO" | "ODOO" | "IT";
export type CampaignStatus = "DRAFT" | "READY" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
export type CampaignCompanyStatus = "ADDED" | "REVIEW" | "REMOVED";
export type OdooStatus =
  | "NOT_CHECKED"
  | "NEW"
  | "EXISTING_CONTACT"
  | "EXISTING_CUSTOMER"
  | "ACTIVE_OPPORTUNITY"
  | "PREVIOUSLY_CONTACTED"
  | "POSSIBLE_DUPLICATE"
  | "CHECK_FAILED";
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

export interface Company {
  id: number;
  name: string;
  normalized_name: string;
  website: string | null;
  domain: string | null;
  country: string | null;
  city: string | null;
  industry: string | null;
  main_phone: string | null;
  main_phone_normalized: string | null;
  main_email: string | null;
  company_size: string | null;
  description: string | null;
  odoo_status: OdooStatus;
  creator: UserBrief | null;
  created_at: string;
  updated_at: string;
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
  my_campaigns: number;
  draft_campaigns: number;
  lusha_credits_used: number;
  recent_companies: Company[];
  recent_activity: Activity[];
}

export interface SystemStatus {
  version: string;
  environment: string;
  integrations: { name: string; status: string; detail: string }[];
}
