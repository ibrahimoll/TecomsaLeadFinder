import { CampaignForm } from "@/components/campaign-form";
import { PageHeader } from "@/components/ui";

export default function NewCampaignPage() {
  return (
    <div className="max-w-4xl">
      <PageHeader
        title="New campaign"
        description="Campaigns are saved as drafts. No external searches are run in this version."
      />
      <CampaignForm />
    </div>
  );
}
