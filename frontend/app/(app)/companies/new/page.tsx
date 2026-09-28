import { CompanyForm } from "@/components/company-form";
import { PageHeader } from "@/components/ui";

export default function NewCompanyPage() {
  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Add company"
        description="Manually add a company to the master database. Its Odoo status starts as “Not checked”."
      />
      <CompanyForm />
    </div>
  );
}
