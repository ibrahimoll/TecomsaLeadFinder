"use client";

import { useParams } from "next/navigation";

import { AdminGuard } from "@/components/admin-guard";
import { Alert, Loading, PageHeader } from "@/components/ui";
import { UserForm } from "@/components/user-form";
import { useApi } from "@/lib/api";
import type { User } from "@/types";

function EditUser() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading } = useApi<User>(`/users/${id}`);
  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error.message}</Alert>;
  if (!data) return null;
  return (
    <div className="max-w-3xl">
      <PageHeader title="Edit user" description={data.email} />
      <UserForm user={data} />
    </div>
  );
}

export default function EditUserPage() {
  return (
    <AdminGuard>
      <EditUser />
    </AdminGuard>
  );
}
