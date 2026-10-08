import { CampaignForm } from "@/components/campaign-form";
import { PageHeader } from "@/components/ui";

export default function NewCampaignPage() {
  return (
    <div className="max-w-6xl">
      <PageHeader
        breadcrumbs={[{ label: "Campaigns", href: "/campaigns" }, { label: "New campaign" }]}
        title="New campaign"
        description="Define who you are targeting. It is saved as a draft; then add companies from Companies or Find companies."
      />
      <CampaignForm />
    </div>
  );
}
