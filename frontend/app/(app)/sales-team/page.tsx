"use client";

import { Users } from "lucide-react";
import { useState } from "react";

import { RequireCapability } from "@/components/guard";
import { Alert, Avatar, Badge, Button, DataTable, EmptyState, PageHeader, Section, Select } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth";
import type { Page, SalespersonRow, User } from "@/types";

function LinkUser({ row, users, onSaved }: { row: SalespersonRow; users: User[]; onSaved: () => void }) {
  const [value, setValue] = useState(String(row.salesperson.user?.id ?? ""));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const dirty = value !== String(row.salesperson.user?.id ?? "");

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api(`/salespeople/${row.salesperson.id}`, { method: "PATCH", body: { user_id: value ? Number(value) : null } });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not link user.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Select aria-label={`LeadFinder user for ${row.salesperson.name}`} className="w-48" value={value} onChange={(e) => setValue(e.target.value)}>
        <option value="">Not linked</option>
        {users.map((u) => (
          <option key={u.id} value={u.id}>
            {u.name}
          </option>
        ))}
      </Select>
      {dirty && (
        <Button size="sm" onClick={save} disabled={saving}>
          Save
        </Button>
      )}
      {error && <span className="text-xs text-danger">{error}</span>}
    </div>
  );
}

export default function SalesTeamPage() {
  const me = useCurrentUser();
  const { data, error, loading, reload } = useApi<SalespersonRow[]>("/salespeople");
  const users = useApi<Page<User>>(me.capabilities.manage_users ? "/users" : null, { page_size: 100, is_active: true });

  return (
    <RequireCapability capability="view_crm">
      <PageHeader
        title="Sales team"
        description="TECOMSA salespeople found in Odoo imports, and what they own."
      />
      {me.capabilities.manage_users && (
        <div className="mb-4">
          <Alert tone="info">Link a salesperson to their LeadFinder account so future phases can route protected companies and leads to them.</Alert>
        </div>
      )}
      <Section flush>
        <DataTable
          caption="Salespeople"
          rows={data ?? undefined}
          loading={loading}
          error={error?.message}
          onRetry={reload}
          rowKey={(r) => r.salesperson.id}
          empty={
            <EmptyState
              icon={<Users className="h-5 w-5" />}
              title="No salespeople yet"
              description="Salespeople are created automatically from the Salesperson column of Odoo imports."
            />
          }
          columns={[
            {
              key: "name",
              header: "Salesperson",
              cell: (r) => (
                <div className="flex items-center gap-2.5">
                  <Avatar name={r.salesperson.name} size="sm" />
                  <span className="font-medium">{r.salesperson.name}</span>
                  {!r.salesperson.active && <Badge>Inactive</Badge>}
                </div>
              ),
            },
            { key: "open", header: "Open CRM records", align: "right", cell: (r) => r.open_records },
            { key: "all", header: "All CRM records", align: "right", cell: (r) => r.crm_records },
            { key: "contacts", header: "Odoo contacts", align: "right", cell: (r) => r.odoo_contacts },
            { key: "companies", header: "Companies owned", align: "right", cell: (r) => r.companies },
            {
              key: "user",
              header: "LeadFinder account",
              cell: (r) =>
                me.capabilities.manage_users && users.data ? (
                  <LinkUser row={r} users={users.data.items} onSaved={reload} />
                ) : (
                  <span className="text-fg-muted">{r.salesperson.user?.name ?? "Not linked"}</span>
                ),
            },
          ]}
        />
      </Section>
    </RequireCapability>
  );
}
