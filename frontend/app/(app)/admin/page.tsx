"use client";

import { Plus } from "lucide-react";
import { Suspense, useCallback, useState } from "react";

import { RequireCapability } from "@/components/guard";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  ConfirmDialog,
  DataTable,
  DescriptionList,
  EmptyState,
  ErrorState,
  PageHeader,
  Pagination,
  RowLink,
  SearchInput,
  Section,
  Skeleton,
  Tabs,
  Toolbar,
  type Tone,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth";
import { ROLE_LABEL } from "@/lib/constants";
import { formatDateTime } from "@/lib/format";
import { useDebouncedSearch, useUrlState } from "@/lib/use-url-state";
import type { AuditLog, IntegrationState, Page, SystemStatus, User } from "@/types";

type TabKey = "users" | "audit" | "integrations" | "settings";
const PAGE_SIZE = 50;

function UsersTab() {
  const me = useCurrentUser();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [pending, setPending] = useState<User | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const { data, error, loading, reload } = useApi<Page<User>>("/users", { q, page, page_size: PAGE_SIZE });

  async function toggleActive(user: User) {
    setBusy(true);
    setActionError(null);
    try {
      await api(`/users/${user.id}`, { method: "PATCH", body: { is_active: !user.is_active } });
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not update user.");
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  return (
    <Section flush>
      <Toolbar end={<ButtonLink href="/admin/users/new" size="sm"><Plus className="h-3.5 w-3.5" aria-hidden /> Create user</ButtonLink>}>
        <SearchInput
          className="w-full sm:w-72"
          value={q}
          onChange={(v) => {
            setQ(v);
            setPage(1);
          }}
          placeholder="Search name or email"
          label="Search users"
        />
      </Toolbar>
      {actionError && (
        <div className="px-4 pt-3">
          <Alert>{actionError}</Alert>
        </div>
      )}
      <DataTable
        caption="Users"
        rows={data?.items}
        loading={loading}
        error={error?.message}
        onRetry={reload}
        rowKey={(u) => u.id}
        empty={<EmptyState title="No users found" />}
        columns={[
          {
            key: "name",
            header: "Name",
            cell: (u) => (
              <div className="leading-tight">
                <RowLink href={`/admin/users/${u.id}`}>{u.name}</RowLink>
                <p className="text-xs text-fg-muted">{u.email}</p>
              </div>
            ),
          },
          { key: "role", header: "Role", cell: (u) => ROLE_LABEL[u.role] },
          { key: "odoo", header: "Odoo user", cell: (u) => (u.odoo_user_id ? `#${u.odoo_user_id}` : <span className="text-fg-subtle">Not linked</span>) },
          { key: "status", header: "Status", cell: (u) => (u.is_active ? <Badge tone="success" dot>Active</Badge> : <Badge tone="neutral" dot>Deactivated</Badge>) },
          { key: "login", header: "Last sign-in", cell: (u) => <span className="text-fg-muted">{formatDateTime(u.last_login_at)}</span> },
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (u) =>
              u.id !== me.id && (
                <Button variant={u.is_active ? "danger" : "secondary"} size="sm" onClick={() => setPending(u)}>
                  {u.is_active ? "Deactivate" : "Activate"}
                </Button>
              ),
          },
        ]}
      />
      {data && (
        <div className="border-t border-border">
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
        </div>
      )}
      <ConfirmDialog
        open={pending !== null}
        title={pending?.is_active ? `Deactivate ${pending?.name}?` : `Activate ${pending?.name}?`}
        confirmLabel={pending?.is_active ? "Deactivate" : "Activate"}
        tone={pending?.is_active ? "danger" : "primary"}
        busy={busy}
        onConfirm={() => pending && toggleActive(pending)}
        onClose={() => setPending(null)}
      >
        {pending?.is_active
          ? "They are signed out immediately and can no longer sign in. Their records and history are kept."
          : "They will be able to sign in again with their existing password."}
      </ConfirmDialog>
    </Section>
  );
}

function AuditTab() {
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const commit = useCallback((v: string) => {
    setAction(v);
    setPage(1);
  }, []);
  const [text, setText] = useDebouncedSearch(action, commit);
  const { data, error, loading, reload } = useApi<Page<AuditLog>>("/audit", { action: action.trim(), page, page_size: PAGE_SIZE });

  return (
    <Section flush>
      <Toolbar>
        <SearchInput className="w-full sm:w-72" value={text} onChange={setText} placeholder="Exact action, e.g. import.completed" label="Filter by action" />
      </Toolbar>
      <DataTable
        caption="Audit log"
        rows={data?.items}
        loading={loading}
        error={error?.message}
        onRetry={reload}
        rowKey={(a) => a.id}
        empty={<EmptyState title="No audit records" description={action ? "No entries with this action." : undefined} />}
        columns={[
          { key: "at", header: "Time", cell: (a) => <span className="text-fg-muted">{formatDateTime(a.created_at)}</span> },
          { key: "user", header: "User", cell: (a) => a.user?.name ?? <span className="text-fg-subtle">System / anonymous</span> },
          { key: "action", header: "Action", cell: (a) => <code className="font-mono text-xs">{a.action}</code> },
          { key: "entity", header: "Entity", cell: (a) => (a.entity_type ? `${a.entity_type} #${a.entity_id ?? "—"}` : "—") },
          {
            key: "details",
            header: "Details",
            className: "whitespace-normal",
            cell: (a) => (
              <code className="block max-w-[420px] break-all font-mono text-2xs text-fg-muted">{a.metadata ? JSON.stringify(a.metadata) : "—"}</code>
            ),
          },
        ]}
      />
      {data && (
        <div className="border-t border-border">
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
        </div>
      )}
    </Section>
  );
}

const STATE: Record<IntegrationState, { tone: Tone; label: string }> = {
  CONFIGURED: { tone: "success", label: "Configured" },
  NOT_CONFIGURED: { tone: "neutral", label: "Not configured" },
  DISABLED: { tone: "neutral", label: "Disabled" },
  ERROR: { tone: "danger", label: "Error" },
};

function useStatus() {
  return useApi<SystemStatus>("/settings/status");
}

function IntegrationsTab() {
  const { data, error, loading, reload } = useStatus();
  if (error) return <Section><ErrorState message={error.message} onRetry={reload} /></Section>;
  return (
    <Section flush title="Integrations" description="Read-only. External providers stay disconnected until they are genuinely built and configured.">
      <DataTable
        caption="Integrations"
        rows={data?.integrations}
        loading={loading}
        rowKey={(i) => i.name}
        columns={[
          { key: "name", header: "Integration", cell: (i) => <span className="font-medium">{i.name}</span> },
          { key: "status", header: "State", cell: (i) => <Badge tone={STATE[i.status].tone} dot>{STATE[i.status].label}</Badge> },
          { key: "detail", header: "Notes", className: "whitespace-normal text-fg-muted", cell: (i) => i.detail },
        ]}
      />
    </Section>
  );
}

function SettingsTab() {
  const { data, error, loading, reload } = useStatus();
  if (error) return <Section><ErrorState message={error.message} onRetry={reload} /></Section>;
  if (loading || !data) return <Skeleton className="h-32 w-full" />;
  return (
    <Section title="Application settings" description="Configured through environment variables on the server (see README).">
      <DescriptionList
        columns={3}
        items={[
          { label: "Version", value: data.version },
          { label: "Environment", value: <code className="font-mono text-xs">{data.environment}</code> },
          { label: "Last Odoo import", value: formatDateTime(data.last_odoo_import_at) },
          { label: "Sales Managers can import", value: data.managers_can_import ? "Yes" : "No (MANAGERS_CAN_IMPORT=false)" },
        ]}
      />
    </Section>
  );
}

function AdminView() {
  const [state, setState] = useUrlState(["tab"] as const);
  const tab = (state.tab || "users") as TabKey;
  return (
    <>
      <div className="mb-4">
        <Tabs<TabKey>
          label="Administration sections"
          value={tab}
          onChange={(key) => setState({ tab: key === "users" ? "" : key })}
          tabs={[
            { key: "users", label: "Users" },
            { key: "audit", label: "Audit log" },
            { key: "integrations", label: "Integrations" },
            { key: "settings", label: "Settings" },
          ]}
        />
      </div>
      <div role="tabpanel" tabIndex={0} className="focus-visible:outline-offset-4">
        {tab === "users" && <UsersTab />}
        {tab === "audit" && <AuditTab />}
        {tab === "integrations" && <IntegrationsTab />}
        {tab === "settings" && <SettingsTab />}
      </div>
    </>
  );
}

export default function AdminPage() {
  return (
    <RequireCapability capability="manage_users">
      <PageHeader title="Administration" description="Users, audit trail and system status." />
      <Suspense>
        <AdminView />
      </Suspense>
    </RequireCapability>
  );
}
