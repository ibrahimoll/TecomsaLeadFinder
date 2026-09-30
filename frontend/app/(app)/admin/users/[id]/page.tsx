"use client";

import { useParams } from "next/navigation";

import { RequireCapability } from "@/components/guard";
import { ErrorState, PageHeader, Section, Skeleton } from "@/components/ui";
import { UserForm } from "@/components/user-form";
import { useApi } from "@/lib/api";
import type { User } from "@/types";

function EditUser() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading, reload } = useApi<User>(`/users/${id}`);
  if (error) return <Section><ErrorState message={error.message} onRetry={reload} /></Section>;
  if (loading || !data) return <Skeleton className="h-64 w-full max-w-3xl" />;
  return (
    <div className="max-w-3xl">
      <PageHeader
        breadcrumbs={[{ label: "Administration", href: "/admin" }, { label: data.name }]}
        title="Edit user"
        description={data.email}
      />
      <UserForm user={data} />
    </div>
  );
}

export default function EditUserPage() {
  return (
    <RequireCapability capability="manage_users">
      <EditUser />
    </RequireCapability>
  );
}
