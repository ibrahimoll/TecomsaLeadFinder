import { Badge, type Tone } from "@/components/ui";
import { CAMPAIGN_STATUS_LABEL, DIVISION_LABEL, ODOO_STATUS_LABEL, SOURCE_LABEL } from "@/lib/constants";
import type { CampaignStatus, CompanySource, CrmLead, DiscoveryState, DiscoveryStatus, Division, ImportStatus, OdooStatus } from "@/types";

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
    <Badge tone={campaignTone[status]} dot>
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

const discoveryState: Record<DiscoveryState, { tone: Tone; label: string }> = {
  AVAILABLE: { tone: "success", label: "New · available" },
  EXISTING_LEADFINDER: { tone: "neutral", label: "Already in LeadFinder" },
  EXISTING_ODOO_CONTACT: { tone: "warning", label: "Existing Odoo contact" },
  EXISTING_CRM_LEAD: { tone: "warning", label: "Existing CRM lead" },
  OPEN_OPPORTUNITY: { tone: "warning", label: "Open opportunity" },
  CUSTOMER: { tone: "warning", label: "Existing customer" },
  LOST_OPPORTUNITY: { tone: "warning", label: "Lost opportunity" },
  PROTECTED: { tone: "warning", label: "Protected" },
  DUPLICATE: { tone: "neutral", label: "Duplicate" },
};

/** TECOMSA status of one discovered candidate. */
export function DiscoveryStateBadge({ state }: { state: DiscoveryState }) {
  const s = discoveryState[state];
  return (
    <Badge tone={s.tone} dot>
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
