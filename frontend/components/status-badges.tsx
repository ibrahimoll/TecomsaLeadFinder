import { Badge, type Tone } from "@/components/ui";
import { CAMPAIGN_STATUS_LABEL, DIVISION_LABEL, ODOO_STATUS_LABEL, SOURCE_LABEL } from "@/lib/constants";
import type {
  CampaignStatus,
  CompanySource,
  CrmLead,
  DiscoveryConfidence,
  DiscoveryState,
  DiscoveryStatus,
  Division,
  ImportStatus,
  LeadQualification,
  ResearchStatus,
  ScaleSignal,
  WebsiteStatus,
  OdooStatus,
} from "@/types";

/*
 * One colour meaning across the product:
 *   green   available / completed / ready
 *   amber   exists in Odoo (protected) / needs attention
 *   red     failed / error
 *   blue    in progress / informational
 *   grey    not checked / inactive / skipped
 * The label carries the detail (Customer, Open lead…), not the colour.
 */
const crmTone: Record<OdooStatus, Tone> = {
  NOT_CHECKED: "neutral",
  AVAILABLE: "success",
  CUSTOMER: "warning",
  EXISTING_OPPORTUNITY: "warning",
  EXISTING_LEAD: "warning",
  LOST_OPPORTUNITY: "warning",
  EXISTING_CONTACT: "warning",
  PREVIOUSLY_CONTACTED: "warning",
  CHECK_FAILED: "danger",
};

export function CrmStatusBadge({ status }: { status: OdooStatus }) {
  return (
    <Badge tone={crmTone[status]} dot>
      {ODOO_STATUS_LABEL[status]}
    </Badge>
  );
}

/** State of one Odoo CRM record. */
export function CrmStateBadge({ lead }: { lead: Pick<CrmLead, "is_won" | "is_lost"> }) {
  if (lead.is_won) return <Badge tone="success" dot>Won</Badge>;
  if (lead.is_lost) return <Badge tone="neutral" dot>Lost</Badge>;
  return <Badge tone="info" dot>Open</Badge>;
}

const campaignTone: Record<CampaignStatus, Tone> = {
  DRAFT: "neutral",
  READY: "accent",
  RUNNING: "info",
  COMPLETED: "success",
  FAILED: "danger",
  CANCELLED: "neutral",
};

export function CampaignStatusBadge({ status }: { status: CampaignStatus }) {
  return (
    <Badge tone={campaignTone[status]} dot live={status === "RUNNING"}>
      {CAMPAIGN_STATUS_LABEL[status]}
    </Badge>
  );
}

export function DivisionBadge({ division }: { division: Division }) {
  return <Badge>{DIVISION_LABEL[division]}</Badge>;
}

/** `subtle` renders plain text in dense tables; demo data always stays flagged as fictional. */
export function SourceBadge({ source, label, subtle }: { source: CompanySource; label?: string; subtle?: boolean }) {
  const text = label ?? SOURCE_LABEL[source] ?? source;
  if (subtle && source !== "DEMO") return <span className="text-fg-muted">{text}</span>;
  return <Badge tone={source === "DEMO" ? "warning" : "neutral"}>{text}</Badge>;
}

const importTone: Record<ImportStatus, Tone> = {
  PREVIEW: "info",
  COMPLETED: "success",
  FAILED: "danger",
  CANCELLED: "neutral",
};
const importLabel: Record<ImportStatus, string> = {
  PREVIEW: "Preview · not imported",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

export function ImportStatusBadge({ status }: { status: ImportStatus }) {
  return (
    <Badge tone={importTone[status]} dot>
      {importLabel[status]}
    </Badge>
  );
}

export const DISCOVERY_STATE: Record<DiscoveryState, { tone: Tone; label: string }> = {
  AVAILABLE: { tone: "success", label: "Available" },
  EXISTING_LEADFINDER: { tone: "neutral", label: "Already in LeadFinder" },
  EXISTING_ODOO_CONTACT: { tone: "warning", label: "Existing Odoo contact" },
  EXISTING_CRM_LEAD: { tone: "warning", label: "Existing CRM lead" },
  OPEN_OPPORTUNITY: { tone: "warning", label: "Open opportunity" },
  CUSTOMER: { tone: "warning", label: "Existing customer" },
  LOST_OPPORTUNITY: { tone: "warning", label: "Lost opportunity" },
  PROTECTED: { tone: "warning", label: "Protected" },
  POSSIBLE_ODOO_MATCH: { tone: "info", label: "Possible Odoo match" },
  DUPLICATE: { tone: "neutral", label: "Duplicate" },
  MERGED_BRANCH: { tone: "neutral", label: "Merged branch" },
  CLOSED: { tone: "danger", label: "Closed" },
  WRONG_INDUSTRY: { tone: "danger", label: "Wrong industry" },
  LOW_CONFIDENCE: { tone: "neutral", label: "Low confidence" },
  RESERVED: { tone: "warning", label: "Reserved by a colleague" },
};

const confidence: Record<DiscoveryConfidence, { tone: Tone; label: string }> = {
  HIGH: { tone: "success", label: "High" },
  MEDIUM: { tone: "info", label: "Medium" },
  LOW: { tone: "neutral", label: "Low" },
};

/** Discovery confidence: how well the sources support the company. Not size or fit. */
export function ConfidenceBadge({ value }: { value: DiscoveryConfidence }) {
  return (
    <Badge tone={confidence[value].tone} dot>
      {confidence[value].label}
    </Badge>
  );
}

/** TECOMSA status of one discovered candidate. */
export function DiscoveryStateBadge({ state }: { state: DiscoveryState }) {
  const s = DISCOVERY_STATE[state];
  return (
    <Badge tone={s.tone} dot live={status === "QUEUED" || status === "SEARCHING" || status === "PROCESSING"}>
      {s.label}
    </Badge>
  );
}

const discoveryStatus: Record<DiscoveryStatus, { tone: Tone; label: string }> = {
  QUEUED: { tone: "info", label: "Queued" },
  SEARCHING: { tone: "info", label: "Searching" },
  PROCESSING: { tone: "info", label: "Processing" },
  COMPLETED: { tone: "success", label: "Completed" },
  PARTIAL: { tone: "warning", label: "Partially completed" },
  FAILED: { tone: "danger", label: "Failed" },
};

export function DiscoveryStatusBadge({ status }: { status: DiscoveryStatus }) {
  const s = discoveryStatus[status];
  return (
    <Badge tone={s.tone} dot>
      {s.label}
    </Badge>
  );
}

// ---- Phase 2: research & qualification ------------------------------------------------------

const QUALIFICATION: Record<LeadQualification, { label: string; tone: Tone }> = {
  QUALIFIED: { label: "Qualified", tone: "success" },
  NEEDS_REVIEW: { label: "Needs review", tone: "warning" },
  LOW_PRIORITY: { label: "Low priority", tone: "neutral" },
  INSUFFICIENT_EVIDENCE: { label: "Insufficient evidence", tone: "neutral" },
};
const RESEARCH: Record<ResearchStatus, { label: string; tone: Tone }> = {
  QUEUED: { label: "Queued", tone: "info" },
  RESEARCHING: { label: "Researching", tone: "info" },
  RESEARCHED: { label: "Qualifying", tone: "info" },
  COMPLETED: { label: "Researched", tone: "success" },
  RESEARCH_FAILED: { label: "Research failed", tone: "danger" },
  QUALIFICATION_FAILED: { label: "Qualification failed", tone: "danger" },
};
export const WEBSITE_STATUS: Record<WebsiteStatus, { label: string; tone: Tone }> = {
  ACTIVE: { label: "Active", tone: "success" },
  REDIRECTED: { label: "Redirected", tone: "info" },
  PLACEHOLDER: { label: "Placeholder", tone: "warning" },
  PARKED: { label: "Parked domain", tone: "danger" },
  FOR_SALE: { label: "Domain for sale", tone: "danger" },
  EMPTY: { label: "Empty page", tone: "warning" },
  UNREACHABLE: { label: "Unreachable", tone: "warning" },
  BLOCKED: { label: "Blocks visits", tone: "neutral" },
  NO_WEBSITE: { label: "No website", tone: "neutral" },
  VALIDATION_FAILED: { label: "Not checked", tone: "neutral" },
};
const SCALE: Record<ScaleSignal, Tone> = { STRONG: "success", MODERATE: "info", LIMITED: "neutral", UNKNOWN: "neutral" };

export function QualificationBadge({ value }: { value: LeadQualification }) {
  return <Badge tone={QUALIFICATION[value].tone} dot>{QUALIFICATION[value].label}</Badge>;
}

export function ResearchStatusBadge({ value }: { value: ResearchStatus }) {
  return <Badge tone={RESEARCH[value].tone} dot>{RESEARCH[value].label}</Badge>;
}

export function WebsiteStatusBadge({ value }: { value: WebsiteStatus | null }) {
  if (!value) return <span className="text-fg-subtle">—</span>;
  return <Badge tone={WEBSITE_STATUS[value].tone}>{WEBSITE_STATUS[value].label}</Badge>;
}

export function ScaleBadge({ value }: { value: ScaleSignal }) {
  return <Badge tone={SCALE[value]}>{value === "UNKNOWN" ? "Unknown" : value.charAt(0) + value.slice(1).toLowerCase()}</Badge>;
}

/** "84 · High" fit score with its (separate) confidence, plus a bar coloured by band (70+ / 40-69 / below). */
export function FitScore({ score, confidence }: { score: number; confidence: string }) {
  const bar = score >= 70 ? "bg-success" : score >= 40 ? "bg-warning" : "bg-fg-subtle/60";
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap tabular" title={`${score} / 100`}>
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-surface-muted" aria-hidden>
        <span className={`block h-full origin-left animate-grow-x rounded-full ${bar}`} style={{ width: `${Math.max(3, Math.min(100, score))}%` }} />
      </span>
      <span className="w-6 text-right font-semibold text-fg">{score}</span>
      <span className="text-fg-subtle">{confidence.charAt(0) + confidence.slice(1).toLowerCase()}</span>
    </span>
  );
}
