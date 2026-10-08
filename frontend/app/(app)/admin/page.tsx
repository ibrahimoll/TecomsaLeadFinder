"use client";

import clsx from "clsx";
import { CheckCircle2, Code2, PlugZap, Plus, ScrollText, Settings2, ShieldCheck, Tag, Users, XCircle, type LucideIcon } from "lucide-react";
import { Suspense, useCallback, useState, type ReactNode } from "react";

import { RequireCapability } from "@/components/guard";
import { Alert, Avatar, Badge, Button, ButtonLink, ConfirmDialog, CountUp, DataTable, EmptyState, ErrorState, PageHeader, Pagination, RowLink, SearchInput, Section, Skeleton, Tabs, TimeAgo, Toolbar, toast, type Tone } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth";
import { ROLE_LABEL } from "@/lib/constants";
import { formatDateTime } from "@/lib/format";
import { useDebouncedSearch, useUrlState } from "@/lib/use-url-state";
import type { AuditLog, IntegrationState, Page, SystemStatus, User } from "@/types";

type TabKey = "users" | "audit" | "integrations" | "settings";
const PAGE_SIZE = 50;

const signedInRecently = (at: string | null) => !!at && Date.now() - new Date(at).getTime() < 3_600_000;

/** Who is on the team, by role, from the users on this page. */
function TeamStrip({ users, total }: { users: User[]; total: number }) {
  const count = (pred: (u: User) => boolean) => users.filter(pred).length;
  const items = [
    { label: "Users", value: total, dot: "bg-fg" },
    { label: "Administrators", value: count((u) => u.role === "ADMIN"), dot: "bg-accent" },
    { label: "Sales managers", value: count((u) => u.role === "SALES_MANAGER"), dot: "bg-info" },
    { label: "Salespeople", value: count((u) => u.role !== "ADMIN" && u.role !== "SALES_MANAGER"), dot: "bg-fg-subtle" },
    { label: "Active in last hour", value: count((u) => signedInRecently(u.last_login_at)), dot: "bg-success" },
  ];
  return (
    <ul className="stagger flex flex-wrap gap-x-6 gap-y-2 border-b border-border px-4 py-3">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-2 text-[12.5px] text-fg-muted">
          <span className={clsx("h-2 w-2 rounded-full", i.dot)} aria-hidden />
          <span className="font-display text-[15px] font-semibold tabular text-fg">
            <CountUp value={i.value} reveal={`users:${i.label}`} />
          </span>
          {i.label}
        </li>
      ))}
    </ul>
  );
}

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
      toast.success(user.is_active ? `${user.name} deactivated` : `${user.name} reactivated`);
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
      {data && <TeamStrip users={data.items} total={data.total} />}
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
        rowHref={(u) => `/admin/users/${u.id}`}
        empty={<EmptyState title="No users found" />}
        columns={[
          {
            key: "name",
            header: "Name",
            cell: (u) => (
              <div className="flex items-center gap-2.5 py-1">
                <span className="relative">
                  <Avatar name={u.name} size="md" />
                  {signedInRecently(u.last_login_at) && (
                    <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 animate-pop-in rounded-full border-2 border-surface bg-success" title="Signed in within the last hour" />
                  )}
                </span>
                <div className="leading-tight">
                  <RowLink href={`/admin/users/${u.id}`}>{u.name}</RowLink>
                  {u.id === me.id && <span className="ml-1.5 rounded-full bg-accent px-1.5 py-px text-[10px] font-semibold text-white">You</span>}
                  <p className="text-xs text-fg-muted">{u.email}</p>
                </div>
              </div>
            ),
          },
          {
            key: "role",
            header: "Role",
            cell: (u) => (
              <span
                className={clsx(
                  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
                  u.role === "ADMIN" ? "bg-accent-soft text-accent" : u.role === "SALES_MANAGER" ? "bg-info-soft text-info" : "bg-surface-muted text-fg-muted",
                )}
              >
                {u.role === "ADMIN" && <ShieldCheck className="h-3 w-3" aria-hidden />}
                {ROLE_LABEL[u.role]}
              </span>
            ),
          },
          { key: "odoo", header: "Odoo user", cell: (u) => (u.odoo_user_id ? `#${u.odoo_user_id}` : <span className="text-fg-subtle">Not linked</span>) },
          { key: "status", header: "Status", cell: (u) => (u.is_active ? <Badge tone="success" dot>Active</Badge> : <Badge tone="neutral" dot>Deactivated</Badge>) },
          { key: "login", header: "Last sign-in", cell: (u) => (u.last_login_at ? <span className="text-fg-muted"><TimeAgo value={u.last_login_at} /></span> : <span className="text-fg-subtle">Never</span>) },
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (u) =>
              u.id !== me.id && (
                <Button
                  variant={u.is_active ? "danger" : "secondary"}
                  size="sm"
                  className="opacity-50 transition-opacity duration-150 focus-visible:opacity-100 group-hover:opacity-100"
                  onClick={() => setPending(u)}
                >
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

/** "import.completed" as a tag coloured by its area, so related events group visually. */
const AREA_TONE: Record<string, string> = {
  auth: "bg-info-soft text-info",
  user: "bg-accent-soft text-accent",
  import: "bg-success-soft text-success",
  company: "bg-warning-soft text-warning",
  campaign: "bg-accent-soft text-accent",
  discovery: "bg-info-soft text-info",
  research: "bg-success-soft text-success",
};

function ActionTag({ action }: { action: string }) {
  const area = action.split(".")[0] ?? "";
  const failed = /fail|error|denied/.test(action);
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[11.5px]",
        failed ? "bg-danger-soft text-danger" : AREA_TONE[area] ?? "bg-surface-muted text-fg-muted",
      )}
    >
      <Tag className="h-3 w-3 opacity-70" aria-hidden />
      {action}
    </span>
  );
}

/** Metadata as key/value chips (first few), with the raw JSON one click away. */
function AuditDetails({ metadata }: { metadata: Record<string, unknown> | null }) {
  if (!metadata || Object.keys(metadata).length === 0) return <span className="text-fg-subtle">—</span>;
  const entries = Object.entries(metadata);
  const show = entries.slice(0, 4);
  const fmt = (v: unknown) => (typeof v === "object" ? JSON.stringify(v) : String(v));
  return (
    <div className="max-w-[460px] py-1">
      <div className="flex flex-wrap gap-1">
        {show.map(([k, v]) => (
          <span key={k} className="inline-flex max-w-full items-center gap-1 truncate rounded bg-surface-muted px-1.5 py-0.5 text-[11px] ring-1 ring-inset ring-border">
            <span className="text-fg-subtle">{k}</span>
            <span className="truncate font-medium text-fg">{fmt(v)}</span>
          </span>
        ))}
      </div>
      {entries.length > show.length || show.some(([, v]) => fmt(v).length > 40) ? (
        <details className="mt-1">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[11px] text-fg-subtle hover:text-fg [&::-webkit-details-marker]:hidden">
            <Code2 className="h-3 w-3" aria-hidden /> Raw JSON
          </summary>
          <code className="mt-1 block break-all rounded bg-surface-muted p-2 font-mono text-2xs text-fg-muted">{JSON.stringify(metadata, null, 1)}</code>
        </details>
      ) : null}
    </div>
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
          {
            key: "user",
            header: "User",
            cell: (a) =>
              a.user ? (
                <span className="inline-flex items-center gap-2">
                  <Avatar name={a.user.name} size="sm" /> {a.user.name}
                </span>
              ) : (
                <span className="text-fg-subtle">System / anonymous</span>
              ),
          },
          { key: "action", header: "Action", cell: (a) => <ActionTag action={a.action} /> },
          { key: "entity", header: "Entity", cell: (a) => (a.entity_type ? `${a.entity_type} #${a.entity_id ?? "—"}` : "—") },
          {
            key: "details",
            header: "Details",
            className: "whitespace-normal",
            cell: (a) => <AuditDetails metadata={a.metadata} />,
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
  ACTIVE: { tone: "success", label: "Active" },
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
  if (loading || !data) return <Skeleton className="h-40 w-full rounded-lg" />;
  const connected = data.integrations.filter((i) => i.status === "CONFIGURED").length;
  const tint = (s: IntegrationState) => (s === "CONFIGURED" ? "bg-success" : s === "ERROR" ? "bg-danger" : "bg-border-strong");
  return (
    <div>
      {/* Health summary: one segment per integration, filling in order. */}
      <div className="mb-4 rounded-lg border border-border bg-surface p-4 shadow-card">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="font-display text-[15px] font-semibold">
            <span className="tabular text-success">
              <CountUp value={connected} reveal="integrations" />
            </span>{" "}
            of {data.integrations.length} integrations connected
          </p>
          <p className="text-[12.5px] text-fg-muted">Read-only. External providers stay disconnected until they are genuinely built and configured.</p>
        </div>
        <div className="mt-3 flex gap-1" aria-hidden>
          {data.integrations.map((i, n) => (
            <span key={i.name} className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-muted">
              <span className={clsx("block h-full origin-left animate-grow-x", tint(i.status))} style={{ animationDelay: `${n * 90}ms` }} />
            </span>
          ))}
        </div>
      </div>
      <ul className="stagger grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {data.integrations.map((i, n) => {
          const ok = i.status === "CONFIGURED";
          const bad = i.status === "ERROR";
          const Icon = ok ? CheckCircle2 : bad ? XCircle : PlugZap;
          return (
            <li
              key={i.name}
              className={clsx(
                "group relative flex gap-3 overflow-hidden rounded-lg border bg-surface p-4 shadow-card transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-0.5 hover:shadow-card-hover",
                ok ? "border-border hover:border-success/40" : bad ? "border-danger/30" : "border-dashed border-border-strong",
              )}
            >
              <span className={clsx("absolute inset-x-0 top-0 h-0.5 origin-left animate-grow-x", tint(i.status))} style={{ animationDelay: `${120 + n * 90}ms` }} aria-hidden />
              <span
                className={clsx(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-transform duration-200 group-hover:scale-110",
                  ok ? "bg-success/10 text-success" : bad ? "bg-danger/10 text-danger" : "bg-surface-muted text-fg-subtle",
                )}
                aria-hidden
              >
                <Icon className="h-[18px] w-[18px] animate-pop-in" style={{ animationDelay: `${200 + n * 90}ms`, animationDuration: "300ms", animationFillMode: "both" }} />
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-display text-[14px] font-semibold">{i.name}</p>
                  <Badge tone={STATE[i.status].tone} dot>
                    {STATE[i.status].label}
                  </Badge>
                </div>
                {i.detail && <p className="mt-1 text-[12.5px] text-fg-muted">{i.detail}</p>}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SettingsTab() {
  const { data, error, loading, reload } = useStatus();
  if (error) return <Section><ErrorState message={error.message} onRetry={reload} /></Section>;
  if (loading || !data) return <Skeleton className="h-32 w-full" />;
  return (
    <div>
      <p className="mb-3 text-[13px] text-fg-muted">Configured through environment variables on the server (see README).</p>
      <ul className="stagger grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {(
          [
            { label: "Version", value: data.version, icon: Tag },
            { label: "Environment", value: <code className="font-mono">{data.environment}</code>, icon: Settings2 },
          ] as { label: string; value: ReactNode; hint?: string; icon: LucideIcon }[]
        ).map((item) => (
          <li key={item.label} className="rounded-lg border border-border bg-surface p-4 shadow-card">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[12.5px] font-medium text-fg-muted">{item.label}</p>
              <item.icon className="h-4 w-4 text-fg-subtle" aria-hidden />
            </div>
            <p className="mt-2 font-display text-[17px] font-semibold text-fg">{item.value}</p>
            {item.hint && <p className="mt-0.5 font-mono text-[11px] text-fg-subtle">{item.hint}</p>}
          </li>
        ))}
      </ul>
    </div>
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
            { key: "users", label: "Users", icon: Users },
            { key: "audit", label: "Audit log", icon: ScrollText },
            { key: "integrations", label: "Integrations", icon: PlugZap },
            { key: "settings", label: "Settings", icon: Settings2 },
          ]}
        />
      </div>
      <div key={tab} role="tabpanel" tabIndex={0} className="animate-page-in focus-visible:outline-offset-4">
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
