import { CompanyForm } from "@/components/company-form";
import { PageHeader } from "@/components/ui";

export default function NewCompanyPage() {
  return (
    <div className="max-w-3xl">
      <PageHeader
        breadcrumbs={[{ label: "Companies", href: "/companies" }, { label: "Add company" }]}
        title="Add company"
        description="LeadFinder checks it against imported Odoo data as soon as it is saved."
      />
      <CompanyForm />
    </div>
  );
}
