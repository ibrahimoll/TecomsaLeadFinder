"use client";

import { Target } from "lucide-react";
import Link from "next/link";
import { Suspense, useCallback, useState } from "react";

import { LeadStatusBadge, NextActivityText, OpportunityModal, SyncBadge } from "@/components/opportunity";

import {
  FitScore,
  QualificationBadge,
  ScaleBadge,
  WEBSITE_STATUS,
  WebsiteStatusBadge,
} from "@/components/status-badges";
import { Avatar, Button, DataTable, EmptyState, FilterPills, PageHeader, Pagination, RowLink, SearchInput, Section, Select, Toolbar } from "@/components/ui";
import { useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { displayDomain } from "@/lib/domain";
import { formatDate } from "@/lib/format";
import { useDebouncedSearch, useUrlState } from "@/lib/use-url-state";
import type { Page, QualifiedLead, WebsiteStatus } from "@/types";

const PAGE_SIZE = 50;
const KEYS = ["q", "qualification", "min_odoo", "min_frinzo", "confidence", "scale", "industry", "website_status", "dm", "sales", "sort", "page"] as const;
const FITS = ["50", "60", "70", "80", "90"];

function LeadsView() {
  const privileged = isPrivileged(useCurrentUser());
  const [filters, setFilters] = useUrlState(KEYS);
  const commitSearch = useCallback((q: string) => setFilters({ q }), [setFilters]);
  const [search, setSearch] = useDebouncedSearch(filters.q, commitSearch);
  const page = Number(filters.page) || 1;
  const [creating, setCreating] = useState<QualifiedLead | null>(null);
  const { data, error, loading, reload } = useApi<Page<QualifiedLead>>("/research/leads", {
    q: filters.q,
    qualification: filters.qualification,
    min_odoo: filters.min_odoo,
    min_frinzo: filters.min_frinzo,
    confidence: filters.confidence,
    scale: filters.scale,
    industry: filters.industry,
    website_status: filters.website_status,
    decision_makers: filters.dm,
    sales: filters.sales,
    sort: filters.sort || "rank",
    page,
    page_size: PAGE_SIZE,
  });

  return (
    <Section flush>
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
        <FilterPills<string>
          label="Qualification"
          value={filters.qualification}
          onChange={(qualification) => setFilters({ qualification })}
          options={[
            { value: "", label: "All researched" },
            { value: "QUALIFIED", label: "Qualified", dot: "bg-success" },
            { value: "NEEDS_REVIEW", label: "Needs review", dot: "bg-warning" },
            { value: "LOW_PRIORITY", label: "Low priority", dot: "bg-fg-subtle" },
            { value: "INSUFFICIENT_EVIDENCE", label: "Insufficient evidence", dot: "bg-border-strong" },
          ]}
        />
        {data && (
          <span className="ml-auto text-xs text-fg-muted">
            <span className="font-semibold tabular text-fg">{data.total.toLocaleString()}</span> {data.total === 1 ? "lead" : "leads"}
          </span>
        )}
      </div>
      <Toolbar
        end={
          <Select aria-label="Sort by" className="w-[170px]" value={filters.sort || "rank"} onChange={(e) => setFilters({ sort: e.target.value === "rank" ? "" : e.target.value })}>
            <option value="rank">Best first</option>
            <option value="odoo">Odoo fit</option>
            <option value="frinzo">Frinzo fit</option>
            <option value="scale">Scale signals</option>
            <option value="confidence">Confidence</option>
            <option value="researched">Last researched</option>
          </Select>
        }
      >
        <SearchInput className="w-full sm:w-56" value={search} onChange={setSearch} placeholder="Search company" label="Search leads" />
        <Select aria-label="Minimum Odoo fit" className="w-[130px]" value={filters.min_odoo} onChange={(e) => setFilters({ min_odoo: e.target.value })}>
          <option value="">Odoo fit</option>
          {FITS.map((f) => <option key={f} value={f}>Odoo ≥ {f}</option>)}
        </Select>
        <Select aria-label="Minimum Frinzo fit" className="w-[130px]" value={filters.min_frinzo} onChange={(e) => setFilters({ min_frinzo: e.target.value })}>
          <option value="">Frinzo fit</option>
          {FITS.map((f) => <option key={f} value={f}>Frinzo ≥ {f}</option>)}
        </Select>
        <Select aria-label="Confidence" className="w-[130px]" value={filters.confidence} onChange={(e) => setFilters({ confidence: e.target.value })}>
          <option value="">Confidence</option>
          <option value="HIGH">High</option>
          <option value="MEDIUM">Medium</option>
          <option value="LOW">Low</option>
        </Select>
        <Select aria-label="Scale signals" className="w-[130px]" value={filters.scale} onChange={(e) => setFilters({ scale: e.target.value })}>
          <option value="">Scale</option>
          <option value="STRONG">Strong</option>
          <option value="MODERATE">Moderate</option>
          <option value="LIMITED">Limited</option>
          <option value="UNKNOWN">Unknown</option>
        </Select>
        <Select aria-label="Website" className="w-[150px]" value={filters.website_status} onChange={(e) => setFilters({ website_status: e.target.value })}>
          <option value="">Website</option>
          {(Object.keys(WEBSITE_STATUS) as WebsiteStatus[]).map((s) => <option key={s} value={s}>{WEBSITE_STATUS[s].label}</option>)}
        </Select>
        <Select aria-label="Decision makers" className="w-[170px]" value={filters.dm} onChange={(e) => setFilters({ dm: e.target.value })}>
          <option value="">Decision makers</option>
          <option value="none">No decision-maker yet</option>
          <option value="found">Decision-maker found</option>
          <option value="high">High-confidence contact</option>
          <option value="email">Email available</option>
          <option value="phone">Phone available</option>
          <option value="review">Needs review</option>
        </Select>
        <Select aria-label="Sales workflow" className="w-[160px]" value={filters.sales} onChange={(e) => setFilters({ sales: e.target.value })}>
          <option value="">Sales workflow</option>
          <option value="ready">Ready</option>
          <option value="not_synced">Not in Odoo yet</option>
          <option value="created">Opportunity created</option>
          <option value="contacted">Contacted</option>
          <option value="follow_up">Follow-up</option>
          <option value="due">Follow-up due</option>
          <option value="meeting">Meeting</option>
          <option value="proposal">Proposal</option>
          <option value="won">Won</option>
          <option value="lost">Lost</option>
        </Select>
        <SearchInput className="w-full sm:w-40" value={filters.industry} onChange={(v) => setFilters({ industry: v })} placeholder="Industry" label="Industry" />
      </Toolbar>
      <DataTable<QualifiedLead, number>
        caption="Qualified leads"
        rows={data?.items}
        loading={loading}
        error={error?.message}
        onRetry={reload}
        rowKey={(r) => r.company_id}
        rowHref={(r) => `/companies/${r.company_id}?tab=intelligence`}
        empty={
          <EmptyState
            icon={<Target />}
            title="No researched companies yet"
            description="Open a company (or select several on the Companies page) and research it. Qualified leads appear here."
          />
        }
        columns={[
          {
            key: "name",
            header: "Company",
            cell: (r) => (
              <div className="flex min-w-[220px] max-w-[300px] items-center gap-2.5 py-1">
                <Avatar name={r.name} size="sm" domain={r.final_url ? displayDomain(r.final_url) : null} />
                <div className="min-w-0 leading-tight">
                  <span className="block truncate">
                    <RowLink href={`/companies/${r.company_id}?tab=intelligence`}>{r.name}</RowLink>
                  </span>
                  <span className="block truncate text-[11.5px] text-fg-subtle">{[r.industry, r.city].filter(Boolean).join(" · ") || "—"}</span>
                </div>
              </div>
            ),
          },
          { key: "scale", header: "Scale signals", cell: (r) => <ScaleBadge value={r.scale_signal} /> },
          { key: "web", header: "Website", cell: (r) => <WebsiteStatusBadge value={r.website_status} /> },
          { key: "odoo", header: "Odoo fit", cell: (r) => <FitScore score={r.odoo_fit_score} confidence={r.odoo_confidence} /> },
          { key: "frinzo", header: "Frinzo fit", cell: (r) => <FitScore score={r.frinzo_fit_score} confidence={r.frinzo_confidence} /> },
          {
            key: "q",
            header: "Qualification",
            cell: (r) => (
              <span className="flex flex-col items-start gap-0.5 py-1" title={r.status_reason ?? undefined}>
                <QualificationBadge value={r.qualification_status} />
                <span className="text-[11px] text-fg-subtle">{r.priority.charAt(0) + r.priority.slice(1).toLowerCase()} priority</span>
              </span>
            ),
          },
          {
            key: "dm",
            header: "Decision maker",
            cell: (r) =>
              r.primary_contact ? (
                <Link href={`/companies/${r.company_id}?tab=people`} className="flex max-w-[200px] flex-col py-1 leading-tight hover:underline">
                  <span className="truncate font-medium text-fg">{r.primary_contact.name}</span>
                  <span className="truncate text-[11.5px] text-fg-subtle">
                    {r.primary_contact.score}/100 · {r.primary_contact.email_status === "VERIFIED" || r.primary_contact.email_status === "AVAILABLE" ? "email ✓" : "no email"}
                    {r.primary_contact.phone_status === "AVAILABLE" ? " · phone ✓" : ""}
                  </span>
                </Link>
              ) : (
                <span className="text-[12px] text-fg-subtle">{r.decision_makers ? `${r.decision_makers} found${r.needs_review ? " · review" : ""}` : "Not searched"}</span>
              ),
          },
          ...(privileged ? [{ key: "owner", header: "Owner", cell: (r: QualifiedLead) => r.owner ? <span className="inline-flex items-center gap-2 text-fg-muted"><Avatar name={r.owner.name} size="sm" />{r.owner.name}</span> : <span className="text-fg-subtle">—</span> }] : []),
          {
            key: "sales",
            header: "Sales",
            cell: (r) => {
              const s = r.sales;
              if (!s) return <span className="text-fg-subtle">—</span>;
              return (
                <div className="flex min-w-[150px] flex-col items-start gap-1 py-1 text-[11.5px]" title={r.researched_at ? `Researched ${formatDate(r.researched_at)}` : undefined}>
                  <span className="flex flex-wrap items-center gap-1">
                    <LeadStatusBadge value={s.lead_status} />
                    {s.sync_status !== "NOT_SYNCED" && <SyncBadge value={s.sync_status} stage={s.odoo_stage} />}
                  </span>
                  {s.sync_status === "NOT_SYNCED" && s.lead_status && r.qualification_status === "QUALIFIED" ? (
                    <Button size="sm" variant="secondary" onClick={() => setCreating(r)}>Create opportunity</Button>
                  ) : (
                    s.lead_status && <NextActivityText value={s.next_activity} />
                  )}
                </div>
              );
            },
          },
        ]}
      />
      {creating && (
        <OpportunityModal
          open
          companyId={creating.company_id}
          companyName={creating.name}
          onClose={() => setCreating(null)}
          onDone={() => {
            setCreating(null);
            void reload();
          }}
        />
      )}
      {data && (
        <div className="border-t border-border">
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={(p) => setFilters({ page: String(p) })} />
        </div>
      )}
    </Section>
  );
}

export default function LeadsPage() {
  return (
    <>
      <PageHeader
        title="Qualified leads"
        description="Researched companies ranked by qualification, priority and the better of their Odoo / Frinzo fit. Fit and confidence are shown separately; nothing is estimated without evidence."
      />
      <Suspense>
        <LeadsView />
      </Suspense>
    </>
  );
}
