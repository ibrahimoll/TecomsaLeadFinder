"use client";

import { useParams } from "next/navigation";

import { CompanyForm } from "@/components/company-form";
import { Alert, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { CompanyDetail } from "@/types";

export default function EditCompanyPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading } = useApi<CompanyDetail>(`/companies/${id}`);

  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error.message}</Alert>;
  if (!data) return null;
  if (!data.can_edit) return <Alert tone="amber">You can only edit companies you created.</Alert>;
  return (
    <div className="max-w-3xl">
      <PageHeader title="Edit company" description={data.name} />
      <CompanyForm company={data} />
    </div>
  );
}
