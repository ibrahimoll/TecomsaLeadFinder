"use client";

import clsx from "clsx";
import { Building2, Check, ChevronRight, ExternalLink, MapPin, Minus, Radar, RotateCw, Target, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { RadarScope } from "@/components/radar-scope";
import { ConfidenceBadge, DISCOVERY_STATE, DiscoveryStateBadge, DiscoveryStatusBadge } from "@/components/status-badges";
import {
  Alert,
  Avatar,
  Button,
  CountUp,
  DataTable,
  EmptyState,
  ErrorState,
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
import type { DiscoveryGroup, DiscoveryResult, DiscoveryResultsPage, DiscoveryRun, DiscoveryState } from "@/types";
import { safeHref } from "@/lib/url";

const ACTIVE = new Set(["QUEUED", "SEARCHING", "PROCESSING"]);
const PAGE_SIZE = 50;

/** Honest stage list: only what the backend reported, in order, drawn as a live pipeline. */
function Progress({ run }: { run: DiscoveryRun }) {
  const steps = run.progress.filter((p) => p.key !== "queued" || run.progress.length === 1);
  return (
    <Section title="Scanning public business data" description="This page updates by itself. You can leave it; the search keeps running." flush>
      {/* Indeterminate scan bar: work is happening even between stage updates. */}
      <span className="relative block h-0.5 overflow-hidden bg-accent-soft" aria-hidden>
        <span className="absolute inset-y-0 left-0 w-1/3 animate-[loading-bar_1.4s_ease-in-out_infinite] bg-accent" />
      </span>
      <ol className="px-5 py-5">
        {steps.map((p, i) => (
          <li key={p.key} className="relative flex animate-page-in gap-4 pb-6 last:pb-0">
            {i < steps.length - 1 && (
              <span className="absolute bottom-0 left-[13px] top-8 w-0.5 overflow-hidden rounded-full bg-border" aria-hidden>
                <span className={clsx("block w-full bg-success transition-[height] duration-300 ease-out", p.state === "done" ? "h-full" : "h-0")} />
              </span>
            )}
            <span className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center" aria-hidden>
              {p.state === "active" && <span className="absolute inset-0 animate-ping rounded-full bg-accent/30" />}
              <span
                className={clsx(
                  "relative flex h-7 w-7 items-center justify-center rounded-full text-white",
                  p.state === "active" ? "bg-accent shadow-[0_0_0_4px_rgb(var(--accent)/0.15)]" : p.state === "failed" ? "animate-pop-in bg-danger" : "animate-pop-in bg-success",
                )}
              >
                {p.state === "active" ? (
                  <Radar className="h-3.5 w-3.5 animate-spin [animation-duration:2s]" />
                ) : p.state === "failed" ? (
                  <X className="h-3.5 w-3.5" strokeWidth={3} />
                ) : (
                  <Check className="h-3.5 w-3.5" strokeWidth={3} />
                )}
              </span>
            </span>
            <div className="min-w-0 pt-1 text-[13px]">
              <p className={clsx("font-medium", p.state === "active" ? "text-fg" : "text-fg-muted")}>
                {p.label}
                {p.state === "active" && <span className="ml-1 inline-block animate-pulse text-accent">…</span>}
              </p>
              {p.detail && <p key={p.detail} className="mt-0.5 animate-[fade-in_300ms_ease-out] tabular text-fg-muted">{p.detail}</p>}
            </div>
          </li>
        ))}
      </ol>
    </Section>
  );
}

/** Progress toward the requested number of credible companies. */
function TargetRing({ pct }: { pct: number }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setDrawn(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  return (
    <div className="relative h-[68px] w-[68px] shrink-0" aria-hidden>
      <svg viewBox="0 0 68 68" className="h-full w-full -rotate-90">
        <circle cx="34" cy="34" r={r} fill="none" strokeWidth="6" className="stroke-surface-muted" />
        <circle
          cx="34"
          cy="34"
          r={r}
          fill="none"
          strokeWidth="6"
          strokeLinecap="round"
          stroke="currentColor"
          className="text-success transition-[stroke-dashoffset] duration-500 ease-out"
          strokeDasharray={c}
          strokeDashoffset={drawn ? c * (1 - pct / 100) : c}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-display text-[13px] font-semibold tabular text-fg">{pct}%</span>
    </div>
  );
}

function FunnelStep({ step, label, value, hint, icon: Icon }: { step: number; label: string; value: number; hint?: string; icon: typeof MapPin }) {
  return (
    <div className="relative bg-surface p-5">
      <div className="flex items-center gap-2 text-xs font-medium text-fg-muted">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-surface-muted text-fg-muted" aria-hidden>
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className="text-fg-subtle">{step}.</span> {label}
      </div>
      <p className="mt-2 font-display text-[26px] font-semibold leading-8 tracking-[-0.02em] tabular text-fg">
        <CountUp value={value} reveal={`funnel:${label}`} />
      </p>
      {hint && <p className="mt-0.5 text-xs text-fg-subtle">{hint}</p>}
      <ChevronRight className="absolute -right-2.5 top-1/2 z-10 hidden h-5 w-5 -translate-y-1/2 rounded-full bg-surface p-0.5 text-fg-subtle ring-1 ring-border sm:block" aria-hidden />
    </div>
  );
}

/** The search as a funnel (places -> companies -> credible), then where every other record went. */
function Summary({ run, page, onGroup }: { run: DiscoveryRun; page: DiscoveryResultsPage | null; onGroup: (group: DiscoveryGroup) => void }) {
  const states = page?.state_counts ?? {};
  const conf = page?.confidence_counts ?? {};
  const pct = Math.min(100, Math.round((run.new_company_count / Math.max(run.requested_count, 1)) * 100));
  const all: { label: string; value: number; dot: string; group: DiscoveryGroup }[] = [
    { label: "low confidence", value: states.LOW_CONFIDENCE ?? 0, dot: "bg-fg-subtle", group: "low" },
    { label: "already in LeadFinder", value: run.existing_company_count, dot: "bg-info", group: "known" },
    { label: "protected (in Odoo)", value: run.odoo_protected_count, dot: "bg-warning", group: "protected" },
    { label: "possible Odoo matches", value: states.POSSIBLE_ODOO_MATCH ?? 0, dot: "bg-info/60", group: "possible" },
    { label: "duplicate listings", value: run.duplicate_count, dot: "bg-border-strong", group: "duplicate" },
    { label: "wrong industry", value: states.WRONG_INDUSTRY ?? 0, dot: "bg-danger", group: "rejected" },
    { label: "closed", value: states.CLOSED ?? 0, dot: "bg-danger/60", group: "rejected" },
  ];
  const rest = all.filter((p) => p.value > 0);
  const restTotal = rest.reduce((n, p) => n + p.value, 0);
  return (
    <div className="animate-page-in overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <div className="stagger grid gap-px bg-border sm:grid-cols-[1fr_1fr_minmax(0,1.4fr)]">
        <FunnelStep step={1} label="Places found" value={run.source_match_count} icon={MapPin} hint="Listings that match the industry and area" />
        <FunnelStep
          step={2}
          label="Unique companies"
          value={run.company_count}
          icon={Building2}
          hint={run.branch_count > 0 ? `${run.branch_count.toLocaleString()} branches consolidated` : "After merging duplicate listings"}
        />
        <div className="relative flex items-center gap-4 bg-gradient-to-br from-surface to-success-soft/70 p-5">
          <TargetRing pct={pct} />
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-xs font-medium text-fg-muted">
              <Target className="h-3.5 w-3.5 text-success" aria-hidden /> 3. Credible candidates
            </p>
            <p className="mt-1 font-display text-[32px] font-semibold leading-9 tracking-[-0.02em] tabular text-success">
              <CountUp value={run.new_company_count} reveal="funnel:credible" />
            </p>
            <p className="text-xs text-fg-muted">
              of {run.requested_count} requested
              {page && (
                <>
                  {" "}· <span className="font-medium text-fg">{conf.HIGH ?? 0}</span> high · <span className="font-medium text-fg">{conf.MEDIUM ?? 0}</span> medium
                  confidence
                </>
              )}
            </p>
          </div>
        </div>
      </div>

      {restTotal > 0 && (
        <div className="border-t border-border px-5 py-4">
          <p className="text-xs font-medium text-fg-muted">
            Where the other <span className="tabular text-fg">{restTotal.toLocaleString()}</span> records went{" "}
            <span className="font-normal text-fg-subtle">· click one to see them</span>
          </p>
          <div className="mt-2 flex h-2.5 overflow-hidden rounded-full bg-surface-muted" role="img" aria-label="Breakdown of records not added">
            {rest.map((p) => (
              <span key={p.label} className={clsx("h-full origin-left animate-grow-x", p.dot)} style={{ width: `${(p.value / restTotal) * 100}%` }} />
            ))}
          </div>
          <div className="stagger mt-3 flex flex-wrap gap-1.5">
            {rest.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => onGroup(p.group)}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-fg-muted transition-[border-color,color,box-shadow] hover:border-accent/40 hover:text-fg hover:shadow-xs"
              >
                <span className={clsx("h-2 w-2 rounded-full", p.dot)} aria-hidden />
                <span className="font-semibold tabular text-fg">{p.value.toLocaleString()}</span> {p.label}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="border-t border-border bg-surface-muted/50 px-5 py-2.5 text-[11.5px] text-fg-subtle">
        {run.summary && <p className="mb-0.5 text-[12.5px] text-fg-muted">{run.summary}</p>}
        Confidence shows how sure we are that the company is real and in this industry. It does not measure company size or how good a fit it
        is.
      </div>
    </div>
  );
}

function Website({ url }: { url: string | null }) {
  if (!url) return <span className="text-fg-subtle">—</span>;
  const label = displayDomain(url) ?? url.replace(/^https?:\/\//, "").replace(/\/$/, "");
  return (
    <a href={safeHref(url)} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-[170px] items-center gap-1 text-fg-muted hover:text-accent hover:underline" title={url}>
      <span className="truncate">{label}</span>
      <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
    </a>
  );
}

/** Why this confidence: the evidence for and against, and the scale signals kept for later research. */
function Why({ r }: { r: DiscoveryResult }) {
  if (!r.confidence) return <span className="text-fg-subtle">—</span>;
  return (
    <details className="group max-w-[260px] text-[11.5px]">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 [&::-webkit-details-marker]:hidden">
        <ConfidenceBadge value={r.confidence} />
        <span className="text-fg-subtle underline decoration-dotted underline-offset-2 group-open:no-underline">Why</span>
      </summary>
      <ul className="mt-1.5 space-y-0.5 leading-snug">
        {r.evidence.map((e) => (
          <li key={e} className="flex gap-1.5 text-fg-muted">
            <Check className="mt-0.5 h-3 w-3 shrink-0 text-success" aria-label="Supports" />
            {e}
          </li>
        ))}
        {r.concerns.map((c) => (
          <li key={c} className="flex gap-1.5 text-fg-muted">
            <Minus className="mt-0.5 h-3 w-3 shrink-0 text-fg-subtle" aria-label="Against" />
            {c}
          </li>
        ))}
      </ul>
      {r.signals.length > 0 && <p className="mt-1 text-fg-subtle">Other details: {r.signals.join(" · ")}</p>}
    </details>
  );
}

/** "Sami El Solh" for "McDonald's Sami El Solh" under McDonald's; the address when the name is just the brand. */
function branchLabel(name: string, company: string, address: string | null): string {
  const fold = (s: string) => s.toLowerCase().replace(/['’`´]/g, "");
  const rest = fold(name).startsWith(fold(company)) ? name.slice(name.length - (fold(name).length - fold(company).length)) : name;
  const label = rest.replace(/^[\s\-–—|/,(]+/, "").trim();
  return label || address || name;
}

/** "3 locations · Beirut + other cities": a company row, not one row per branch. Opens to list them. */
function Locations({ r }: { r: DiscoveryResult }) {
  const count = Math.max(r.company?.location_count ?? 0, r.locations.length);
  if (count < 2) return r.address ? <p className="truncate text-[11.5px] text-fg-subtle" title={r.address}>{r.address}</p> : null;
  const cities = Array.from(new Set(r.locations.map((l) => l.city).filter(Boolean)));
  const where = cities.length ? `${cities[0]}${cities.length > 1 ? " + other locations" : ""}` : "";
  return (
    <details className="text-[11.5px]">
      <summary className="cursor-pointer list-none text-fg-subtle hover:text-fg-muted [&::-webkit-details-marker]:hidden">
        <span className="font-medium text-fg-muted">{count} locations</span>
        {where && ` · ${where}`}
      </summary>
      <ul className="mt-1 space-y-0.5 text-fg-muted">
        {r.locations.map((l, i) => (
          <li key={i} className="truncate" title={[l.name, l.address, l.city].filter(Boolean).join(" · ")}>
            {branchLabel(l.name, r.name, l.address)}
            {l.city && <span className="text-fg-subtle"> — {l.city}</span>}
          </li>
        ))}
        {count > r.locations.length && <li className="text-fg-subtle">+{count - r.locations.length} found by earlier searches</li>}
      </ul>
    </details>
  );
}

const SHOW_REASON = new Set(["CLOSED", "WRONG_INDUSTRY", "LOW_CONFIDENCE", "POSSIBLE_ODOO_MATCH"]);

function Results({ run }: { run: DiscoveryRun }) {
  const [f, setF] = useUrlState(["group", "q", "source", "sort", "page", "confidence", "city", "state", "activity"] as const);
  const group = (f.group || "available") as DiscoveryGroup;
  const page = Number(f.page) || 1;
  const commit = useCallback((q: string) => setF({ q }), [setF]);
  const [search, setSearch] = useDebouncedSearch(f.q, commit);
  const data = useApi<DiscoveryResultsPage>(`/discovery/runs/${run.id}/results`, {
    group: group === "all" ? undefined : group,
    q: f.q,
    source: f.source,
    confidence: f.confidence,
    city: f.city,
    state: f.state,
    activity: f.activity,
    sort: f.sort || "rank",
    page,
    page_size: PAGE_SIZE,
  });
  const counts = data.data?.counts;
  const sources = Array.from(new Set([...run.sources, "LEADFINDER"]));
  const filtered = Boolean(f.q || f.source || f.confidence || f.city || f.state || f.activity);

  return (
    <>
      <Summary run={run} page={data.data} onGroup={(g) => setF({ group: g === "available" ? "" : g, page: "" })} />
      <div className="mb-3 mt-4">
        <Tabs<DiscoveryGroup>
          label="Result groups"
          value={group}
          onChange={(key) => setF({ group: key === "available" ? "" : key })}
          tabs={[
            { key: "available", label: "Credible candidates", count: counts?.available },
            { key: "low", label: "Low confidence", count: counts?.low },
            { key: "known", label: "Already in LeadFinder", count: counts?.known },
            { key: "protected", label: "Protected (in Odoo)", count: counts?.protected },
            { key: "possible", label: "Possible Odoo match", count: counts?.possible },
            { key: "duplicate", label: "Merged locations", count: counts?.duplicate },
            { key: "rejected", label: "Rejected", count: counts?.rejected },
            { key: "all", label: "All", count: counts?.all },
          ]}
        />
      </div>
      <Section flush>
        <Toolbar
          end={
            <Select aria-label="Sort by" className="w-[150px]" value={f.sort} onChange={(e) => setF({ sort: e.target.value })}>
              <option value="">Best first</option>
              <option value="confidence">Confidence</option>
              <option value="name">Name A–Z</option>
              <option value="city">City</option>
              <option value="category">Industry</option>
            </Select>
          }
        >
          <SearchInput className="w-full sm:w-56" value={search} onChange={setSearch} placeholder="Search name, city or industry" label="Search results" />
          <Select aria-label="Confidence" className="w-[140px]" value={f.confidence} onChange={(e) => setF({ confidence: e.target.value })}>
            <option value="">Any confidence</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low</option>
          </Select>
          <Select aria-label="City" className="w-[150px]" value={f.city} onChange={(e) => setF({ city: e.target.value })}>
            <option value="">All cities</option>
            {(data.data?.cities ?? []).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
          <Select aria-label="TECOMSA status" className="w-[200px]" value={f.state} onChange={(e) => setF({ state: e.target.value })}>
            <option value="">Any TECOMSA status</option>
            {(Object.keys(DISCOVERY_STATE) as DiscoveryState[]).map((s) => (
              <option key={s} value={s}>
                {DISCOVERY_STATE[s].label}
              </option>
            ))}
          </Select>
          <Select aria-label="Closed or active" className="w-[160px]" value={f.activity} onChange={(e) => setF({ activity: e.target.value })}>
            <option value="">Active & closed</option>
            <option value="active">Active only</option>
            <option value="closed">Closed only</option>
          </Select>
          <Select aria-label="Source" title="Where the listing came from (public map data)" className="w-[150px]" value={f.source} onChange={(e) => setF({ source: e.target.value })}>
            <option value="">All data sources</option>
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
                filtered
                  ? "No results match these filters."
                  : group === "available"
                    ? "No credible candidates in this search."
                    : "Nothing in this group."
              }
              description={group === "available" && counts?.all ? "See the other tabs for why each record was not added." : undefined}
            />
          }
          columns={[
            {
              key: "name",
              header: "Company",
              cell: (r) => (
                <div className="flex min-w-[220px] max-w-[300px] items-start gap-2.5">
                  <Avatar name={r.name} size="sm" domain={r.website ? displayDomain(r.website) : null} />
                  <div className="min-w-0 leading-tight">
                    <span className="block truncate" title={r.name}>
                      {r.company ? <RowLink href={`/companies/${r.company.id}`}>{r.name}</RowLink> : <span className="font-medium">{r.name}</span>}
                    </span>
                    <Locations r={r} />
                  </div>
                </div>
              ),
            },
            {
              key: "industry",
              header: "Industry",
              cell: (r) => (
                <div className="max-w-[200px] leading-tight">
                  <span className="block truncate text-fg-muted" title={r.category ?? undefined}>{r.category ?? "—"}</span>
                  {r.match_reason && <p className="truncate text-[11.5px] text-fg-subtle" title={r.match_reason}>{r.match_reason}</p>}
                </div>
              ),
            },
            { key: "city", header: "City", cell: (r) => <span className="text-fg-muted">{r.city ?? "—"}</span> },
            { key: "website", header: "Website", cell: (r) => <Website url={r.website} /> },
            { key: "phone", header: "Phone", cell: (r) => <span className="whitespace-nowrap tabular text-fg-muted">{r.phone ?? "—"}</span> },
            { key: "confidence", header: "Confidence", cell: (r) => <Why r={r} /> },
            {
              key: "source",
              header: "Source",
              cell: (r) => (
                <span className="whitespace-nowrap text-fg-muted">{(r.sources.length ? r.sources : [r.source]).map((s) => SOURCE_NAME[s] ?? s).join(" + ")}</span>
              ),
            },
            {
              key: "state",
              header: "TECOMSA status",
              cell: (r) => (
                <span className="block py-1 leading-tight" title={r.reason ?? undefined}>
                  {r.duplicate_of_id !== null ? (
                    // A child row (merged-locations audit view): a location of a company, not a lead.
                    <span className="text-[12.5px] text-fg-muted">{r.state === "DUPLICATE" ? "Same place listed again" : "Location"} of {r.company?.name ?? "a company above"}</span>
                  ) : (
                    <DiscoveryStateBadge state={r.state} />
                  )}
                  {r.company?.owner && <span className="mt-0.5 block text-[11.5px] text-fg-subtle">Found by {r.company.owner.name}</span>}
                  {r.state !== "AVAILABLE" && r.reason && (
                    <span
                      className={clsx(
                        "mt-0.5 block max-w-[280px] text-[11.5px] text-fg-subtle",
                        SHOW_REASON.has(r.state) ? "line-clamp-3" : "truncate",
                      )}
                    >
                      {r.reason}
                    </span>
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
      <header
        className="relative mb-6 animate-page-in overflow-hidden rounded-xl text-white shadow-card"
        style={{
          background:
            "radial-gradient(90% 140% at 100% 0%, rgb(214 28 36) 0%, transparent 60%), linear-gradient(135deg, rgb(150 6 12) 0%, rgb(196 18 26) 55%, rgb(120 4 8) 100%)",
        }}
      >
        <div className="relative flex flex-wrap items-center gap-6 px-6 py-6 md:px-8">
          <div className="min-w-0 flex-1">
            <nav aria-label="Breadcrumb">
              <ol className="flex items-center gap-1 text-xs text-white/70">
                <li>
                  <Link href="/discovery" className="transition-colors hover:text-white">
                    Find companies
                  </Link>
                </li>
                <li className="flex items-center gap-1">
                  <ChevronRight className="h-3 w-3" aria-hidden />
                  <span aria-current="page">Search #{run.id}</span>
                </li>
              </ol>
            </nav>
            <h1 className="mt-1.5 text-[26px] font-semibold leading-8 tracking-[-0.02em] text-white">{run.query_label}</h1>
            <div className="stagger mt-3 flex flex-wrap items-center gap-2 text-xs">
              <DiscoveryStatusBadge status={run.status} />
              <span className="whitespace-nowrap rounded-full border border-white/20 bg-white/10 px-2.5 py-0.5">Target {run.requested_count} credible companies</span>
              <span className="whitespace-nowrap rounded-full border border-white/20 bg-white/10 px-2.5 py-0.5">
                {run.sources.length ? run.sources.map((s) => SOURCE_NAME[s] ?? s).join(" + ") : "—"}
              </span>
              <span className="whitespace-nowrap rounded-full border border-white/20 bg-white/10 px-2.5 py-0.5">
                {formatDateTime(run.created_at)} · {run.creator?.name ?? "—"}
              </span>
            </div>
          </div>
          <RadarScope scanning={active} className="hidden w-[112px] shrink-0 sm:block" />
          {!active && (
            <button
              type="button"
              onClick={searchAgain}
              disabled={again}
              className="group inline-flex h-10 items-center gap-2 rounded bg-white px-4 text-[13.5px] font-semibold text-accent shadow-xs transition-[transform,box-shadow] hover:-translate-y-px hover:shadow-card-hover disabled:opacity-60"
            >
              <RotateCw className={clsx("h-3.5 w-3.5 transition-transform duration-500 group-hover:rotate-180", again && "animate-spin")} aria-hidden />
              {again ? "Starting…" : "Search again"}
            </button>
          )}
        </div>
      </header>
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
