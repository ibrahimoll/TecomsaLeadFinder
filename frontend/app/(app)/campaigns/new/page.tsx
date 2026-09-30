import { CampaignForm } from "@/components/campaign-form";
import { PageHeader } from "@/components/ui";

export default function NewCampaignPage() {
  return (
    <div className="max-w-4xl">
      <PageHeader
        breadcrumbs={[{ label: "Campaigns", href: "/campaigns" }, { label: "New campaign" }]}
        title="New campaign"
        description="Saved as a draft. Automatic company discovery starts in a later phase."
      />
      <CampaignForm />
    </div>
  );
}
