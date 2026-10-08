"use client";

import { Briefcase, Building2, Check, Link2, Users } from "lucide-react";
import { useState } from "react";

import { RequireCapability } from "@/components/guard";
import { Alert, Avatar, Badge, Button, DataTable, EmptyState, MetricStrip, PageHeader, Section, Select, toast } from "@/components/ui";
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
      toast.success(value ? `${row.salesperson.name} linked` : `${row.salesperson.name} unlinked`);
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
        <Button size="sm" onClick={save} loading={saving} className="animate-pop-in">
          <Check className="h-3.5 w-3.5" aria-hidden /> Save
        </Button>
      )}
      {error && <span className="text-xs text-danger">{error}</span>}
    </div>
  );
}

/** Open records as a bar relative to the busiest salesperson, so workload reads at a glance. */
function Workload({ value, max }: { value: number; max: number }) {
  return (
    <span className="inline-flex items-center gap-2.5 tabular">
      <span className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-muted" aria-hidden>
        <span className="block h-full origin-left animate-grow-x rounded-full bg-accent" style={{ width: `${(value / max) * 100}%` }} />
      </span>
      <span className="w-8 font-semibold text-fg">{value}</span>
    </span>
  );
}

export default function SalesTeamPage() {
  const me = useCurrentUser();
  const { data, error, loading, reload } = useApi<SalespersonRow[]>(me.capabilities.view_crm ? "/salespeople" : null);
  const users = useApi<Page<User>>(me.capabilities.manage_users ? "/users" : null, { page_size: 100, is_active: true });
  const maxOpen = Math.max(1, ...(data ?? []).map((r) => r.open_records));

  return (
    <RequireCapability capability="view_crm">
      <PageHeader
        title="Sales team"
        description="TECOMSA salespeople found in Odoo imports, and what they own."
      />
      {data && data.length > 0 && (
        <div className="mb-4">
          <MetricStrip
            items={[
              { label: "Salespeople", value: data.length, icon: Users, hint: `${data.filter((r) => r.salesperson.active).length} active` },
              {
                label: "Linked to LeadFinder",
                value: data.filter((r) => r.salesperson.user).length,
                icon: Link2,
                hint: `of ${data.length}`,
              },
              { label: "Open CRM records", value: data.reduce((n, r) => n + r.open_records, 0), icon: Briefcase },
              { label: "Companies owned", value: data.reduce((n, r) => n + r.companies, 0), icon: Building2 },
            ]}
          />
        </div>
      )}
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
                <div className="flex items-center gap-2.5 py-1">
                  <Avatar name={r.salesperson.name} size="md" />
                  <span className="font-medium">{r.salesperson.name}</span>
                  {!r.salesperson.active && <Badge>Inactive</Badge>}
                </div>
              ),
            },
            {
              key: "open",
              header: "Open CRM records",
              cell: (r) => <Workload value={r.open_records} max={maxOpen} />,
            },
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
                  r.salesperson.user ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-success/25 bg-success-soft px-2.5 py-0.5 text-xs font-medium text-success">
                      <Check className="h-3 w-3" strokeWidth={3} aria-hidden /> {r.salesperson.user.name}
                    </span>
                  ) : (
                    <span className="rounded-full border border-dashed border-border-strong px-2.5 py-0.5 text-xs text-fg-subtle">Not linked</span>
                  )
                ),
            },
          ]}
        />
      </Section>
    </RequireCapability>
  );
}
