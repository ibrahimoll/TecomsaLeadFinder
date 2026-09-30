import { Badge, type Tone } from "@/components/ui";
import { CAMPAIGN_STATUS_LABEL, DIVISION_LABEL, ODOO_STATUS_LABEL, SOURCE_LABEL } from "@/lib/constants";
import type { CampaignStatus, CompanySource, Division, ImportStatus, OdooStatus } from "@/types";

const crmTone: Record<OdooStatus, Tone> = {
  NOT_CHECKED: "neutral",
  AVAILABLE: "success",
  CUSTOMER: "accent",
  EXISTING_OPPORTUNITY: "warning",
  EXISTING_LEAD: "warning",
  LOST_OPPORTUNITY: "danger",
  EXISTING_CONTACT: "info",
  PREVIOUSLY_CONTACTED: "info",
  CHECK_FAILED: "danger",
};

export function CrmStatusBadge({ status }: { status: OdooStatus }) {
  return (
    <Badge tone={crmTone[status]} dot>
      {ODOO_STATUS_LABEL[status]}
    </Badge>
  );
}

const campaignTone: Record<CampaignStatus, Tone> = {
  DRAFT: "neutral",
  READY: "accent",
  RUNNING: "info",
  COMPLETED: "success",
  FAILED: "danger",
  CANCELLED: "warning",
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

export function SourceBadge({ source }: { source: CompanySource }) {
  return <Badge tone={source === "DEMO" ? "warning" : "neutral"}>{SOURCE_LABEL[source] ?? source}</Badge>;
}

const importTone: Record<ImportStatus, Tone> = {
  PREVIEW: "info",
  COMPLETED: "success",
  FAILED: "danger",
  CANCELLED: "neutral",
};
const importLabel: Record<ImportStatus, string> = {
  PREVIEW: "Awaiting confirmation",
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
