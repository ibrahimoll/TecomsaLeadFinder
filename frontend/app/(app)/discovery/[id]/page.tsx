"use client";

import clsx from "clsx";
import { Check, ExternalLink, Loader2, Radar, RotateCw, X } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { DiscoveryStateBadge, DiscoveryStatusBadge } from "@/components/status-badges";
import {
  Alert,
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  PageHeader,
  Pagination,
  RowLink,
  SearchInput,
  Section,
  Select,
  Skeleton,
  Tabs,
  Toolbar,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { SOURCE_NAME } from "@/lib/constants";
import { formatDateTime } from "@/lib/format";
import { displayDomain } from "@/lib/domain";
import { useDebouncedSearch, useUrlState } from "@/lib/use-url-state";
import type { DiscoveryGroup, DiscoveryResult, DiscoveryResultsPage, DiscoveryRun } from "@/types";

const ACTIVE = new Set(["QUEUED", "SEARCHING", "PROCESSING"]);
const PAGE_SIZE = 50;

/** Honest stage list: only what the backend reported, in order. */
function Progress({ run }: { run: DiscoveryRun }) {
  return (
    <Section title="Finding companies" description="This page updates by itself. You can leave it; the search keeps running." flush>
      <ol className="divide-y divide-border">
        {run.progress.filter((p) => p.key !== "queued" || run.progress.length === 1).map((p) => (
          <li key={p.key} className="flex items-start gap-3 px-4 py-3">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center" aria-hidden>
              {p.state === "active" ? (
                <Loader2 className="h-4 w-4 animate-spin text-accent" />
              ) : p.state === "failed" ? (
                <X className="h-4 w-4 text-danger" />
              ) : (
                <Check className="h-4 w-4 text-success" />
              )}
            </span>
            <div className="min-w-0 text-[13px]">
              <p className={clsx("font-medium", p.state === "active" ? "text-fg" : "text-fg-muted")}>{p.label}</p>
              {p.detail && <p className="mt-0.5 tabular text-fg-muted">{p.detail}</p>}
            </div>
          </li>
        ))}
      </ol>
    </Section>
  );
}

/** Compact result counts: one line, not a wall of cards. */
function Summary({ run }: { run: DiscoveryRun }) {
  const parts: { label: string; value: number; dot: string }[] = [
    { label: "new", value: run.new_company_count, dot: "bg-success" },
    { label: "protected by Odoo", value: run.odoo_protected_count, dot: "bg-warning" },
    { label: "already in LeadFinder", value: run.existing_company_count, dot: "bg-fg-subtle" },
    { label: "duplicates", value: run.duplicate_count, dot: "bg-border-strong" },
  ];
  return (
    <div className="rounded-lg border border-border bg-surface px-4 py-3 shadow-[0_1px_0_rgb(17_17_20/0.03)]">
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5 text-[13px]">
        <span className="text-fg-muted">
          <span className="text-[18px] font-semibold tracking-tight tabular text-fg">{run.raw_results_count.toLocaleString()}</span> examined
          {run.source_match_count > run.raw_results_count && <> of {run.source_match_count.toLocaleString()} matching</>}
        </span>
        {parts.map((p) => (
          <span key={p.label} className="flex items-center gap-1.5 text-fg-muted">
            <span className={clsx("h-1.5 w-1.5 rounded-full", p.dot)} aria-hidden />
            <span className="font-medium tabular text-fg">{p.value.toLocaleString()}</span> {p.label}
          </span>
        ))}
      </div>
      {run.summary && <p className="mt-1.5 text-[12.5px] text-fg-muted">{run.summary}</p>}
    </div>
  );
}

function Website({ url }: { url: string | null }) {
  if (!url) return <span className="text-fg-subtle">—</span>;
  const label = displayDomain(url) ?? url.replace(/^https?:\/\//, "").replace(/\/$/, "");
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-[190px] items-center gap-1 text-fg-muted hover:text-accent hover:underline" title={url}>
      <span className="truncate">{label}</span>
      <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
    </a>
  );
}

function Results({ run }: { run: DiscoveryRun }) {
  const [f, setF] = useUrlState(["group", "q", "source", "sort", "page"] as const);
  const group = (f.group || "available") as DiscoveryGroup;
  const page = Number(f.page) || 1;
  const commit = useCallback((q: string) => setF({ q }), [setF]);
  const [search, setSearch] = useDebouncedSearch(f.q, commit);
  const data = useApi<DiscoveryResultsPage>(`/discovery/runs/${run.id}/results`, {
    group: group === "all" ? undefined : group,
    q: f.q,
    source: f.source,
    sort: f.sort || "rank",
    page,
    page_size: PAGE_SIZE,
  });
  const counts = data.data?.counts;
  const sources = Array.from(new Set([...run.sources, "LEADFINDER"]));

  return (
    <>
      <div className="mb-3">
        <Tabs<DiscoveryGroup>
          label="Result groups"
          value={group}
          onChange={(key) => setF({ group: key === "available" ? "" : key })}
          tabs={[
            { key: "available", label: "New", count: counts?.available },
            { key: "known", label: "Already in LeadFinder", count: counts?.known },
            { key: "protected", label: "Protected by Odoo", count: counts?.protected },
            { key: "duplicate", label: "Duplicates", count: counts?.duplicate },
            { key: "all", label: "All", count: counts?.all },
          ]}
        />
      </div>
      <Section flush>
        <Toolbar
          end={
            <Select aria-label="Sort by" className="w-[150px]" value={f.sort} onChange={(e) => setF({ sort: e.target.value })}>
              <option value="">Best match first</option>
              <option value="name">Name A–Z</option>
              <option value="city">City</option>
              <option value="category">Category</option>
            </Select>
          }
        >
          <SearchInput className="w-full sm:w-64" value={search} onChange={setSearch} placeholder="Search name, city or category" label="Search results" />
          <Select aria-label="Source" className="w-[160px]" value={f.source} onChange={(e) => setF({ source: e.target.value })}>
            <option value="">All sources</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {SOURCE_NAME[s] ?? s}
              </option>
            ))}
          </Select>
        </Toolbar>
        <DataTable<DiscoveryResult, number>
          caption="Discovered companies"
          rows={data.data?.items}
          loading={data.loading}
          error={data.error?.message}
          onRetry={data.reload}
          rowKey={(r) => r.id}
          rowHref={(r) => (r.company ? `/companies/${r.company.id}` : null)}
          empty={
            <EmptyState
              compact
              icon={<Radar />}
              title={
                group === "available"
                  ? "No new companies in this search."
                  : f.q || f.source
                    ? "No results match these filters."
                    : "Nothing in this group."
              }
              description={group === "available" && counts?.all ? "See the other tabs for why each company was not added." : undefined}
            />
          }
          columns={[
            {
              key: "name",
              header: "Company",
              cell: (r) => (
                <div className="min-w-[220px] max-w-[320px] leading-tight">
                  <span className="block truncate" title={r.name}>
                    {r.company ? <RowLink href={`/companies/${r.company.id}`}>{r.name}</RowLink> : <span className="font-medium">{r.name}</span>}
                  </span>
                  <p className="truncate text-[11.5px] text-fg-subtle">{r.category ?? "—"}</p>
                </div>
              ),
            },
            { key: "city", header: "City", cell: (r) => <span className="text-fg-muted">{r.city ?? "—"}</span> },
            { key: "phone", header: "Phone", cell: (r) => <span className="tabular text-fg-muted">{r.phone ?? "—"}</span> },
            { key: "website", header: "Website", cell: (r) => <Website url={r.website} /> },
            { key: "source", header: "Source", cell: (r) => <span className="text-fg-muted">{SOURCE_NAME[r.source] ?? r.source}</span> },
            {
              key: "state",
              header: "TECOMSA status",
              cell: (r) => (
                <span className="block py-1 leading-tight" title={[r.reason, r.match_reason && `Industry: ${r.match_reason}`].filter(Boolean).join("\n")}>
                  <DiscoveryStateBadge state={r.state} />
                  {r.state !== "AVAILABLE" && r.reason && (
                    <span className="mt-0.5 block max-w-[280px] truncate text-[11.5px] text-fg-subtle">{r.reason}</span>
                  )}
                </span>
              ),
            },
          ]}
        />
        {data.data && (
          <div className="border-t border-border">
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.data.total} onPage={(p) => setF({ page: String(p) })} />
          </div>
        )}
      </Section>
    </>
  );
}

function RunView() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: run, error, reload } = useApi<DiscoveryRun>(`/discovery/runs/${id}`);
  const [again, setAgain] = useState(false);
  const [againError, setAgainError] = useState<string | null>(null);
  const active = run ? ACTIVE.has(run.status) : false;

  // Poll while the search runs.
  useEffect(() => {
    if (!active) return;
    const t = setInterval(reload, 1000);
    return () => clearInterval(t);
  }, [active, reload]);

  async function searchAgain() {
    if (!run) return;
    setAgain(true);
    setAgainError(null);
    try {
      const next = await api<DiscoveryRun>("/discovery/runs", {
        method: "POST",
        body: { country: run.country, city: run.city, industry: run.industry, custom_query: run.custom_query, requested_count: run.requested_count },
      });
      router.push(`/discovery/${next.id}`);
    } catch (err) {
      setAgainError(err instanceof ApiError ? err.message : "The search could not be started.");
      setAgain(false);
    }
  }

  if (error) return <Section><ErrorState message={error.message} onRetry={reload} /></Section>;
  if (!run) {
    return (
      <div className="space-y-4" aria-busy="true">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Find companies", href: "/discovery" }, { label: `Search #${run.id}` }]}
        title={run.query_label}
        meta={
          <>
            <DiscoveryStatusBadge status={run.status} />
            <span>Up to {run.requested_count} companies</span>
            <span>{run.sources.length ? run.sources.map((s) => SOURCE_NAME[s] ?? s).join(", ") : "—"}</span>
            <span>
              {formatDateTime(run.created_at)} · {run.creator?.name ?? "—"}
            </span>
          </>
        }
        actions={
          !active && (
            <Button variant="secondary" onClick={searchAgain} loading={again}>
              <RotateCw className="h-3.5 w-3.5" aria-hidden /> Search again
            </Button>
          )
        }
      />
      <div className="space-y-4">
        {againError && <Alert>{againError}</Alert>}
        {active ? (
          <Progress run={run} />
        ) : (
          <>
            {run.errors.length > 0 && (
              <Alert tone={run.status === "FAILED" ? "danger" : "warning"} title={run.status === "FAILED" ? "The search failed" : "Some sources failed"}>
                <ul className="list-inside list-disc">
                  {run.errors.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              </Alert>
            )}
            {run.status !== "FAILED" && <Summary run={run} />}
            {run.status !== "FAILED" && <Results run={run} />}
            {run.source_version && <p className="text-[11.5px] text-fg-subtle">Data: {run.source_version}.</p>}
          </>
        )}
      </div>
    </>
  );
}

export default function DiscoveryRunPage() {
  return (
    <Suspense>
      <RunView />
    </Suspense>
  );
}
