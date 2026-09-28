"use client";

import { useParams } from "next/navigation";

import { CampaignForm } from "@/components/campaign-form";
import { Alert, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { CampaignDetail } from "@/types";

export default function EditCampaignPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading } = useApi<CampaignDetail>(`/campaigns/${id}`);

  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error.message}</Alert>;
  if (!data) return null;
  if (data.status !== "DRAFT" || !data.can_edit) {
    return <Alert tone="amber">Only draft campaigns you are allowed to manage can be edited.</Alert>;
  }
  return (
    <div className="max-w-4xl">
      <PageHeader title="Edit campaign" description={data.name} />
      <CampaignForm campaign={data} />
    </div>
  );
}
