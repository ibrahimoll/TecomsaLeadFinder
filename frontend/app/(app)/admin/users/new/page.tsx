"use client";

import { RequireCapability } from "@/components/guard";
import { PageHeader } from "@/components/ui";
import { UserForm } from "@/components/user-form";

export default function NewUserPage() {
  return (
    <RequireCapability capability="manage_users">
      <div className="max-w-3xl">
        <PageHeader
          breadcrumbs={[{ label: "Administration", href: "/admin" }, { label: "Create user" }]}
          title="Create user"
          description="Give a TECOMSA team member access to LeadFinder."
        />
        <UserForm />
      </div>
    </RequireCapability>
  );
}
