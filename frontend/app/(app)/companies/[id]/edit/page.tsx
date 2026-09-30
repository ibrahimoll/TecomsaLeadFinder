"use client";

import { useParams } from "next/navigation";

import { CompanyForm } from "@/components/company-form";
import { Alert, ErrorState, PageHeader, Section, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { CompanyDetail } from "@/types";

export default function EditCompanyPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading, reload } = useApi<CompanyDetail>(`/companies/${id}`);

  if (error) return <Section><ErrorState message={error.message} onRetry={reload} /></Section>;
  if (loading || !data) return <Skeleton className="h-64 w-full max-w-3xl" />;
  if (!data.can_edit) return <Alert tone="warning">You can only edit companies you created.</Alert>;
  return (
    <div className="max-w-3xl">
      <PageHeader
        breadcrumbs={[
          { label: "Companies", href: "/companies" },
          { label: data.name, href: `/companies/${data.id}` },
          { label: "Edit" },
        ]}
        title="Edit company"
      />
      <CompanyForm company={data} />
    </div>
  );
}
