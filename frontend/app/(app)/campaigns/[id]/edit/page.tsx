"use client";

import { useParams } from "next/navigation";

import { CampaignForm } from "@/components/campaign-form";
import { Alert, ErrorState, PageHeader, Section, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { CampaignDetail } from "@/types";

export default function EditCampaignPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading, reload } = useApi<CampaignDetail>(`/campaigns/${id}`);

  if (error) return <Section><ErrorState message={error.message} onRetry={reload} /></Section>;
  if (loading || !data) return <Skeleton className="h-64 w-full max-w-4xl" />;
  if (data.status !== "DRAFT" || !data.can_edit) {
    return <Alert tone="warning">Only draft campaigns you are allowed to manage can be edited.</Alert>;
  }
  return (
    <div className="max-w-4xl">
      <PageHeader
        breadcrumbs={[
          { label: "Campaigns", href: "/campaigns" },
          { label: data.name, href: `/campaigns/${data.id}` },
          { label: "Edit" },
        ]}
        title="Edit campaign"
      />
      <CampaignForm campaign={data} />
    </div>
  );
}
