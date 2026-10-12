"use client";

import clsx from "clsx";
import { ArrowRight, FileSpreadsheet, Link2, PlugZap, ScrollText, ServerCog, ShieldCheck, Users, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { Avatar, Badge, CountUp, DataTable, PageHeader, Section, TimeAgo } from "@/components/ui";
import { useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { ROLE_LABEL } from "@/lib/constants";
import { AgentsCard } from "@/components/agents-card";
import { formatDate, formatDateTime } from "@/lib/format";
import type { SystemStatus } from "@/types";
import type { LushaCredits } from "@/types/v2";

const ADMIN_LINKS: { href: string; title: string; description: string; icon: LucideIcon }[] = [
  { href: "/admin", title: "Users", description: "Create accounts, set roles, deactivate people.", icon: Users },
  { href: "/admin?tab=audit", title: "Audit log", description: "Every sign-in, change and deletion, with details.", icon: ScrollText },
  { href: "/admin?tab=integrations", title: "Integrations", description: "Which data providers are connected.", icon: PlugZap },
  { href: "/admin?tab=settings", title: "System", description: "Version, environment and import settings.", icon: ServerCog },
];

function ProfileCard() {
  const user = useCurrentUser();
  const admin = user.role === "ADMIN";
  return (
    <section className="relative overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <span className="absolute inset-x-0 top-0 h-1 origin-left animate-grow-x bg-accent" aria-hidden />
      <div className="flex flex-wrap items-center gap-4 p-5">
        <span className="animate-pop-in">
          <Avatar name={user.name} size="xl" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-display text-[18px] font-semibold">{user.name}</h2>
            <span
              className={clsx(
                "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
                admin ? "bg-accent-soft text-accent" : user.role === "SALES_MANAGER" ? "bg-info-soft text-info" : "bg-surface-muted text-fg-muted",
              )}
            >
              {admin && <ShieldCheck className="h-3 w-3" aria-hidden />}
              {ROLE_LABEL[user.role]}
            </span>
          </div>
          <p className="truncate text-[13px] text-fg-muted">{user.email}</p>
        </div>
      </div>
      <dl className="stagger grid border-t border-border sm:grid-cols-3">
        {[
          { label: "Last sign-in", value: <TimeAgo value={user.last_login_at} /> },
          { label: "Member since", value: formatDate(user.created_at) },
          {
            label: "Odoo user",
            value: user.odoo_user_id ? (
              <span className="inline-flex items-center gap-1 text-success">
                <Link2 className="h-3.5 w-3.5" aria-hidden /> #{user.odoo_user_id}
              </span>
            ) : (
              <span className="text-fg-subtle">Not linked</span>
            ),
          },
        ].map((item) => (
          <div key={item.label} className="border-border px-5 py-3 sm:border-l sm:first:border-l-0">
            <dt className="text-xs text-fg-muted">{item.label}</dt>
            <dd className="mt-0.5 text-[13.5px] font-medium">{item.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Live health line for admins, from the same status the Integrations tab reads. */
function SystemHealth() {
  const { data } = useApi<SystemStatus>("/settings/status");
  if (!data) return <span className="h-4 w-40 animate-pulse rounded bg-surface-muted" />;
  const connected = data.integrations.filter((i) => i.status === "CONFIGURED").length;
  return (
    <span className="flex animate-page-in flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
      <span className="inline-flex items-center gap-1.5">
        <span className="relative flex h-2 w-2" aria-hidden>
          <span className="absolute inset-0 animate-ping rounded-full bg-success/60" style={{ animationIterationCount: 3 }} />
          <span className="relative h-2 w-2 rounded-full bg-success" />
        </span>
        <span className="font-medium tabular text-fg">
          <CountUp value={connected} reveal="settings:integrations" />
        </span>
        of {data.integrations.length} integrations connected
      </span>
      <span>
        Version <span className="font-mono text-fg">{data.version}</span> · <span className="font-mono">{data.environment}</span>
      </span>
    </span>
  );
}

interface LushaLogRow {
  id: number;
  at: string;
  user: string | null;
  company_id: number | null;
  company: string | null;
  action: "search" | "email" | "phone";
  status: string;
  credits: number;
  query: string | null;
  error: string | null;
}

const LUSHA_ACTION = { search: "Search", email: "Email revealed", phone: "Number revealed" } as const;

/** Managers / admins: what LeadFinder spent on Lusha this month, and who searched / revealed what. */
function LushaUsage() {
  const credits = useApi<LushaCredits>("/lusha/credits");
  const log = useApi<LushaLogRow[]>("/lusha/ledger");
  if (!credits.data?.configured) return null;
  const c = credits.data;
  return (
    <Section
      title="Lusha usage"
      description={`${c.spent_this_month} credits this month${c.monthly_budget ? ` of ${c.monthly_budget}` : ""}${c.account?.remaining != null ? ` · ${c.account.remaining} left on the Lusha account` : ""}${c.daily_reveals ? ` · ${c.daily_reveals} reveals per person per day` : ""}`}
      flush
    >
      <DataTable
        caption="Lusha searches and reveals"
        rows={log.data ?? []}
        loading={log.loading}
        rowKey={(r) => r.id}
        columns={[
          { key: "at", header: "When", cell: (r) => formatDateTime(r.at) },
          { key: "user", header: "Who", cell: (r) => r.user ?? "—" },
          { key: "company", header: "Company", cell: (r) => (r.company_id ? <Link href={`/companies/${r.company_id}`} className="hover:text-accent hover:underline">{r.company ?? r.company_id}</Link> : "—") },
          { key: "action", header: "What", cell: (r) => `${LUSHA_ACTION[r.action] ?? r.action}${r.query ? `: “${r.query}”` : ""}` },
          { key: "credits", header: "Credits", cell: (r) => <span className="tabular">{r.credits}</span> },
          { key: "status", header: "Result", cell: (r) => (r.status === "failed" ? <Badge tone="danger">{r.error ?? "failed"}</Badge> : r.status === "not_found" ? <Badge>Lusha had none</Badge> : r.status === "pending" ? <Badge tone="info">Running</Badge> : <Badge tone="success">Done</Badge>) },
        ]}
      />
    </Section>
  );
}

export default function SettingsPage() {
  const user = useCurrentUser();
  return (
    <>
      <PageHeader title="Settings" description="Your account and, for administrators, the workspace." />
      <div className="max-w-4xl space-y-8">
        <ProfileCard />
        <AgentsCard />

        {user.capabilities.run_imports && (
          <Link
            href="/imports"
            className="group flex items-start gap-3 rounded-lg border border-border bg-surface p-4 shadow-card transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-card-hover focus-visible:outline-offset-2"
          >
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
              <FileSpreadsheet className="h-[18px] w-[18px]" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block font-display text-[14px] font-semibold">Directory imports</span>
              <span className="mt-0.5 block text-[12.5px] text-fg-muted">Upload a 5INDEX / Yelleb / Infobel / Kompass / IFP export: companies, decision-makers and their mobiles. History and coverage per directory.</span>
            </span>
            <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-fg-subtle group-hover:text-accent" aria-hidden />
          </Link>
        )}

        {isPrivileged(user) && <LushaUsage />}

        {user.capabilities.manage_users ? (
          <section>
            <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
              <h2 className="font-display text-[15px] font-semibold">Administration</h2>
              {user.role === "ADMIN" && <SystemHealth />}
            </div>
            <ul className="stagger grid gap-3 sm:grid-cols-2">
              {ADMIN_LINKS.map((l) => (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    className="group flex h-full items-start gap-3 rounded-lg border border-border bg-surface p-4 shadow-card transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-card-hover focus-visible:outline-offset-2"
                  >
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent transition-[transform,background-color,color] duration-200 group-hover:scale-110 group-hover:bg-accent group-hover:text-white">
                      <l.icon className="h-[18px] w-[18px]" aria-hidden />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block font-display text-[14px] font-semibold">{l.title}</span>
                      <span className="mt-0.5 block text-[12.5px] text-fg-muted">{l.description}</span>
                    </span>
                    <ArrowRight
                      className="mt-1 h-4 w-4 shrink-0 -translate-x-1 text-fg-subtle opacity-0 transition-[transform,opacity,color] duration-200 group-hover:translate-x-0 group-hover:text-accent group-hover:opacity-100"
                      aria-hidden
                    />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : (
          <p className="animate-page-in rounded-lg border border-dashed border-border-strong px-4 py-3 text-[13px] text-fg-muted">
            Workspace settings are managed by your administrator. Ask them to change your role or link your Odoo user.
          </p>
        )}
      </div>
    </>
  );
}
