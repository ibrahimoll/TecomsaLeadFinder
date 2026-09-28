"use client";

import { AdminGuard } from "@/components/admin-guard";
import { PageHeader } from "@/components/ui";
import { UserForm } from "@/components/user-form";

export default function NewUserPage() {
  return (
    <AdminGuard>
      <div className="max-w-3xl">
        <PageHeader title="Create user" description="Give a TECOMSA team member access to LeadFinder." />
        <UserForm />
      </div>
    </AdminGuard>
  );
}
