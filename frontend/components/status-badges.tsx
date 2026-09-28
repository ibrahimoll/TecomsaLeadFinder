import { Badge } from "@/components/ui";
import { CAMPAIGN_STATUS_LABEL, DIVISION_LABEL, ODOO_STATUS_LABEL } from "@/lib/constants";
import type { CampaignStatus, Division, OdooStatus } from "@/types";

const campaignTone = {
  DRAFT: "gray",
  READY: "blue",
  RUNNING: "purple",
  COMPLETED: "green",
  FAILED: "red",
  CANCELLED: "amber",
} as const;

export function CampaignStatusBadge({ status }: { status: CampaignStatus }) {
  return <Badge tone={campaignTone[status]}>{CAMPAIGN_STATUS_LABEL[status]}</Badge>;
}

const divisionTone = { FRINZO: "purple", ODOO: "blue", IT: "green" } as const;

export function DivisionBadge({ division }: { division: Division }) {
  return <Badge tone={divisionTone[division]}>{DIVISION_LABEL[division]}</Badge>;
}

export function OdooStatusBadge({ status }: { status: OdooStatus }) {
  const tone =
    status === "NOT_CHECKED"
      ? "gray"
      : status === "NEW"
        ? "green"
        : status === "CHECK_FAILED" || status === "POSSIBLE_DUPLICATE"
          ? "red"
          : "amber";
  return <Badge tone={tone}>{ODOO_STATUS_LABEL[status]}</Badge>;
}
