"use client";

import clsx from "clsx";
import { ArrowRight, Briefcase, Building2, CalendarClock, CheckCircle2, DatabaseZap, FileClock, Megaphone, Plus, Radar, ShieldCheck, ShieldQuestion, Sparkles, Target, Trophy, Users, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { ActivityList } from "@/components/activity-list";
import { CampaignStatusBadge } from "@/components/status-badges";
import { Avatar, ButtonLink, CountUp, EmptyState, ErrorState, MetricStrip, Section, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { DIVISION_LABEL } from "@/lib/constants";
import { location } from "@/lib/format";
import type { Company, DashboardSummary, Me, Page } from "@/types";

interface Task {
  icon: LucideIcon;
  title: string;
  detail: string;
  href: string;
  cta: string;
  count?: number;
}

/** "What should I work on now?": next actions derived from real counts, most useful first. */
function workQueue(data: DashboardSummary, user: Me): Task[] {
  const tasks: Task[] = [];
  const noOdoo = data.odoo_crm_records === 0 && data.odoo_contacts === 0;
  const pending = data.latest_imports.filter((r) => r.status === "PREVIEW");
  if (user.capabilities.run_imports && pending.length) {
    tasks.push({
      icon: FileClock,
      title: `${pending.length} import${pending.length === 1 ? "" : "s"} waiting for review`,
      detail: `${pending[0]!.original_filename} was uploaded but not imported yet.`,
      href: `/imports/${pending[0]!.id}`,
      cta: "Review",
    });
  }
  if (noOdoo && data.total_companies > 0) {
    tasks.push({
      icon: ShieldQuestion,
      title: "Check companies against Odoo",
      detail: user.capabilities.run_imports
        ? "No Odoo data yet, so LeadFinder cannot tell which companies TECOMSA already knows."
        : "Ask an administrator to import TECOMSA's Odoo contacts and CRM.",
      href: user.capabilities.run_imports ? "/data-sources/odoo" : "/companies",
      cta: user.capabilities.run_imports ? "Import" : "View",
      count: data.unchecked_companies,
    });
  }
  if (data.available_companies > 0) {
    tasks.push({
      icon: Building2,
      title: "Prospect available companies",
      detail: "No relationship in Odoo: safe to research and approach.",
      href: "/companies?crm_status=AVAILABLE",
      cta: "Open list",
      count: data.available_companies,
    });
  }
  tasks.push({
    icon: Radar,
    title: "Find new companies",
    detail: "Search public business data by industry and area; known and protected companies are filtered out.",
    href: "/discovery",
    cta: "Search",
  });
  if (data.draft_campaigns > 0) {
    tasks.push({
      icon: Megaphone,
      title: "Finish draft campaigns",
      detail: "Set the market, company criteria and roles, then mark them ready.",
      href: "/campaigns?status=DRAFT",
      cta: "Continue",
      count: data.draft_campaigns,
    });
  }
  if (data.my_campaigns === 0) {
    tasks.push({
      icon: Plus,
      title: "Start your first campaign",
      detail: "Define a market, industry and target roles for LeadFinder to work on.",
      href: "/campaigns/new",
      cta: "Create",
    });
  }
  return tasks;
}

function WorkQueue({ tasks }: { tasks: Task[] }) {
  if (tasks.length === 0) {
    return (
      <div className="flex items-center gap-3 px-4 py-4 text-[13px]">
        <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
        <span className="text-fg">You&apos;re all caught up.</span>
        <span className="text-fg-muted">New work appears here as data and campaigns change.</span>
      </div>
    );
  }
  return (
    <ul className="stagger divide-y divide-border">
      {tasks.map((t) => (
        <li key={t.title}>
          <Link href={t.href} className="group flex items-center gap-3.5 px-4 py-3 transition-colors hover:bg-surface-hover/60">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center text-fg-subtle transition-colors group-hover:text-accent">
              <t.icon className="h-4 w-4" strokeWidth={1.75} aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2 text-[13.5px] font-medium text-fg">
                {t.title}
                {t.count !== undefined && (
                  <span className="rounded-sm bg-surface-muted px-1.5 text-[11.5px] font-medium tabular text-fg-muted">{t.count.toLocaleString()}</span>
                )}
              </span>
              <span className="block truncate text-[12.5px] text-fg-muted">{t.detail}</span>
            </span>
            <span className="hidden items-center gap-1 text-xs font-medium text-fg-muted transition-colors group-hover:text-accent sm:flex">
              {t.cta} <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** Share of the company base already known in Odoo vs free to prospect: the one chart that matters here. */
function Coverage({ data }: { data: DashboardSummary }) {
  const total = data.total_companies;
  const parts = [
    { key: "available", label: "Available", value: data.available_companies, bar: "bg-success", href: "/companies?crm_status=AVAILABLE" },
    { key: "protected", label: "Protected", value: data.protected_companies, bar: "bg-warning", href: "/companies?protected=true" },
    { key: "unchecked", label: "Not checked", value: data.unchecked_companies, bar: "bg-border-strong", href: "/companies?crm_status=NOT_CHECKED" },
  ];
  return (
    <div className="px-4 py-4">
      <div className="flex items-baseline justify-between">
        <p className="text-[13px] text-fg-muted">
          <span className="font-display text-[22px] font-semibold tracking-tight tabular text-fg"><CountUp value={total} reveal="coverage" /></span> companies
        </p>
        <Link href="/companies" className="text-xs font-medium text-fg-muted hover:text-fg">
          View all
        </Link>
      </div>
      <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-surface-muted" role="img" aria-label="Company coverage">
        {total > 0 &&
          parts.map((p) =>
            p.value ? <span key={p.key} className={clsx("h-full origin-left animate-grow-x transition-[width] duration-500", p.bar)} style={{ width: `${(p.value / total) * 100}%` }} /> : null,
          )}
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-2">
        {parts.map((p) => (
          <Link key={p.key} href={p.href} className="group rounded px-1 py-0.5 -mx-1 hover:bg-surface-hover/60">
            <dt className="flex items-center gap-1.5 text-[11.5px] text-fg-muted">
              <span className={clsx("h-1.5 w-1.5 rounded-full", p.bar)} aria-hidden />
              {p.label}
            </dt>
            <dd className="text-[15px] font-semibold tabular text-fg">
              {p.value.toLocaleString()}
              <span className="ml-1 text-[11.5px] font-normal text-fg-subtle">{total ? Math.round((p.value / total) * 100) : 0}%</span>
            </dd>
          </Link>
        ))}
      </dl>
    </div>
  );
}

function share(part: number, total: number) {
  return `${total ? Math.round((part / total) * 100) : 0}% of base`;
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export default function DashboardPage() {
  const user = useCurrentUser();
  const { data, error, loading, reload } = useApi<DashboardSummary>("/dashboard");
  const available = useApi<Page<Company>>("/companies", { crm_status: "AVAILABLE", page_size: 6, sort: "created" });
  const firstName = user.name.split(" ")[0];

  if (error) {
    return (
      <Section>
        <ErrorState message={error.message} onRetry={reload} />
      </Section>
    );
  }

  return (
    <>
      {/* Welcome banner in the TECOMSA brand red, echoing the login cover. */}
      <header
        className="relative mb-6 animate-page-in overflow-hidden rounded-xl px-6 py-6 text-white shadow-card md:px-8 md:py-7"
        style={{
          background:
            "radial-gradient(90% 140% at 100% 0%, rgb(214 28 36) 0%, transparent 60%), linear-gradient(135deg, rgb(150 6 12) 0%, rgb(196 18 26) 55%, rgb(120 4 8) 100%)",
        }}
      >
        <div className="relative flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-white/70">LeadFinder AI</p>
            <h1 className="mt-1.5 text-[26px] font-semibold leading-8 tracking-[-0.02em] text-white">
              {greeting()}, {firstName}
            </h1>
            <p className="mt-1 text-[14px] text-white/80">Here is what needs your attention today.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href="/campaigns/new"
              className="inline-flex h-9 items-center gap-1.5 rounded border border-white/25 bg-white/10 px-3.5 text-[13.5px] font-medium text-white transition-colors hover:bg-white/20"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden /> New campaign
            </Link>
            <Link
              href="/discovery"
              className="group inline-flex h-9 items-center gap-1.5 rounded bg-white px-3.5 text-[13.5px] font-semibold text-accent shadow-xs transition-[transform,box-shadow] hover:-translate-y-px hover:shadow-card-hover"
            >
              <Radar className="h-3.5 w-3.5" aria-hidden /> Find companies
              <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
            </Link>
          </div>
        </div>
      </header>

      <div className="mb-5">
        <MetricStrip
          loading={loading && !data}
          items={[
            { label: "Companies", value: data?.total_companies ?? 0, icon: Building2, href: "/companies", hint: "in LeadFinder" },
            {
              label: "Available",
              value: data?.available_companies ?? 0,
              icon: Sparkles,
              href: "/companies?crm_status=AVAILABLE",
              badge: data ? { label: share(data.available_companies, data.total_companies), tone: "success" } : undefined,
            },
            {
              label: "Protected",
              value: data?.protected_companies ?? 0,
              icon: ShieldCheck,
              href: "/companies?protected=true",
              badge: data ? { label: share(data.protected_companies, data.total_companies), tone: "warning" } : undefined,
            },
            {
              label: "My campaigns",
              value: data?.my_campaigns ?? 0,
              icon: Megaphone,
              href: "/campaigns",
              hint: data?.draft_campaigns ? `${data.draft_campaigns} in draft` : undefined,
            },
          ]}
        />
      </div>

      {data?.sales && (
        <div className="mb-5">
          <MetricStrip
            items={[
              { label: "Ready leads", value: data.sales.ready, icon: Target, href: "/my-leads?view=ready", hint: "qualified, not in Odoo yet" },
              { label: "Opportunities", value: data.sales.opportunities, icon: Briefcase, href: "/leads?sales=created", hint: "created in Odoo" },
              {
                label: "Follow-ups due",
                value: data.sales.due,
                icon: CalendarClock,
                href: "/my-leads?view=due",
                badge: data.sales.overdue ? { label: `${data.sales.overdue} overdue`, tone: "danger" } : undefined,
              },
              { label: "Meetings", value: data.sales.meetings, icon: Users, href: "/my-leads?view=meetings" },
              { label: "Won / Lost", value: `${data.sales.won} / ${data.sales.lost}`, icon: Trophy, href: "/leads?sales=won", hint: "from Odoo" },
            ]}
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="stagger min-w-0 space-y-5">
          <Section title="Up next" flush>
            {loading && !data ? (
              <div className="space-y-3 p-4">
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-9 w-full" />
              </div>
            ) : (
              data && <WorkQueue tasks={workQueue(data, user)} />
            )}
          </Section>

          <Section
            title="Available to prospect"
            description="Newest companies with no relationship in TECOMSA's Odoo."
            flush
            actions={
              <ButtonLink href="/companies?crm_status=AVAILABLE" variant="ghost" size="sm">
                View all <ArrowRight className="h-3.5 w-3.5" aria-hidden />
              </ButtonLink>
            }
          >
            {available.loading && !available.data ? (
              <div className="space-y-3 p-4">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-7 w-full" />
                ))}
              </div>
            ) : available.data?.items.length ? (
              <ul className="divide-y divide-border">
                {available.data.items.map((c) => (
                  <li key={c.id}>
                    <Link href={`/companies/${c.id}`} className="flex h-11 items-center gap-3 px-4 transition-colors hover:bg-surface-hover/60">
                      <Avatar name={c.name} size="sm" domain={c.domain} />
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{c.name}</span>
                      <span className="hidden truncate text-[12.5px] text-fg-muted sm:block">{c.industry ?? location(c.city, c.country)}</span>
                      <ArrowRight className="h-3.5 w-3.5 text-fg-subtle" aria-hidden />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                compact
                icon={<Building2 />}
                title={data && data.odoo_contacts + data.odoo_crm_records === 0 ? "Nothing checked against Odoo yet" : "No available companies right now"}
                description="Companies without an Odoo relationship appear here."
              />
            )}
          </Section>

          <Section
            title="Campaigns"
            flush
            actions={
              <ButtonLink href="/campaigns" variant="ghost" size="sm">
                View all <ArrowRight className="h-3.5 w-3.5" aria-hidden />
              </ButtonLink>
            }
          >
            {data && data.recent_campaigns.length === 0 ? (
              <EmptyState
                compact
                icon={<Megaphone />}
                title="No campaigns yet"
                description="A campaign defines the market, company criteria and roles LeadFinder searches for."
                action={
                  <ButtonLink href="/campaigns/new" size="sm">
                    New campaign
                  </ButtonLink>
                }
              />
            ) : (
              <ul className="divide-y divide-border">
                {(data?.recent_campaigns ?? []).map((c) => (
                  <li key={c.id}>
                    <Link href={`/campaigns/${c.id}`} className="flex h-11 items-center gap-3 px-4 transition-colors hover:bg-surface-hover/60">
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{c.name}</span>
                      <span className="hidden text-[12.5px] text-fg-muted sm:block">{DIVISION_LABEL[c.tecomsa_division]}</span>
                      <span className="hidden w-24 text-right text-[12.5px] tabular text-fg-muted sm:block">{c.target_company_count} targets</span>
                      <CampaignStatusBadge status={c.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>

        <div className="stagger min-w-0 space-y-5">
          <Section title="Company coverage" flush>
            {data ? <Coverage data={data} /> : <Skeleton className="m-4 h-20" />}
            {data && user.capabilities.view_crm && (
              <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-[12.5px]">
                <span className="flex items-center gap-2 text-fg-muted">
                  <DatabaseZap className="h-3.5 w-3.5 text-fg-subtle" aria-hidden />
                  Odoo data
                </span>
                <span className="tabular text-fg-muted">
                  <Link href="/crm" className="text-fg hover:underline">{data.odoo_crm_records.toLocaleString()}</Link> CRM ·{" "}
                  <Link href="/crm?tab=contacts" className="text-fg hover:underline">{data.odoo_contacts.toLocaleString()}</Link> contacts
                </span>
              </div>
            )}
          </Section>

          <Section title={isPrivileged(user) ? "Team activity" : "My activity"}>
            <ActivityList items={data?.recent_activity} loading={loading} />
          </Section>
        </div>
      </div>
    </>
  );
}
