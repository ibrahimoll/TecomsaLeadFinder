import { CampaignForm } from "@/components/campaign-form";
import { PageHeader } from "@/components/ui";

export default function NewCampaignPage() {
  return (
    <div className="max-w-6xl">
      <PageHeader
        breadcrumbs={[{ label: "Campaigns", href: "/campaigns" }, { label: "New campaign" }]}
        title="New campaign"
        description="Define who LeadFinder should find. Saved as a draft; automatic company discovery starts in a later phase."
      />
      <CampaignForm />
    </div>
  );
}
