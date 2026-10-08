"use client";

import clsx from "clsx";
import { ExternalLink, Search, SearchX } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";

import { CompanySearch } from "@/components/company-search";
import { RadarScope } from "@/components/radar-scope";
import { Avatar, Badge, Button, CountUp, DataTable, EmptyState, ErrorState, Field, FilterPills, Input, PageHeader, Section, Select, toast, type Tone } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { COMPANY_STATUS, CONFIDENCE, INDUSTRIES, place } from "@/lib/companies";
import { countryNames } from "@/lib/constants";
import { safeHref } from "@/lib/url";
import type { Page } from "@/types";
import type { LeadSearch, LeadSearchResult, LeadSearchStatus } from "@/types/v2";

type Offering = "ANY" | "ODOO" | "FRINZO" | "IT";

const OFFERINGS: { value: Offering; label: string }[] = [
  { value: "ANY", label: "Any" },
  { value: "ODOO", label: "Odoo" },
  { value: "FRINZO", label: "Frinzo" },
  { value: "IT", label: "IT" },
];

const SEARCH_STATUS: Record<LeadSearchStatus, { label: string; tone: Tone }> = {
  pending: { label: "Queued", tone: "neutral" },
  researching: { label: "Searching sources", tone: "info" },
  completed: { label: "Completed", tone: "success" },
  partial: { label: "Partial", tone: "warning" },
  failed: { label: "Failed", tone: "danger" },
};
const POLL_MS = 1000; // while companies are being found
const ENRICH_POLL_MS = 3000; // while only website checks are still running
const COUNT_PRESETS = ["25", "50", "100", "200"];

/** Live progress of a search: companies found against the target, and sources checked. */
function SearchProgress({ s, newCount }: { s: LeadSearch; newCount: number }) {
  const pct = s.requested_count > 0 ? Math.min(100, (s.companies_found / s.requested_count) * 100) : 0;
  const running = s.status === "researching" || s.status === "pending";
  const known = s.companies_found - newCount;
  return (
    <div className="border-b border-border px-4 py-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="font-display text-[26px] font-semibold leading-none tabular text-fg">
          <CountUp value={s.companies_found} />
          <span className="text-[15px] font-medium text-fg-subtle"> / {s.requested_count} companies</span>
        </p>
        <div className="flex flex-wrap gap-1.5 text-xs">
          {newCount > 0 && (
            <span className="animate-pop-in rounded-full bg-accent-soft px-2.5 py-1 font-medium text-accent">
              <CountUp value={newCount} /> new to LeadFinder
            </span>
          )}
          {known > 0 && (
            <span className="animate-pop-in rounded-full bg-surface-muted px-2.5 py-1 font-medium text-fg-muted">
              <CountUp value={known} /> already known
            </span>
          )}
        </div>
      </div>
      <div
        className="relative mt-3 h-2 overflow-hidden rounded-full bg-surface-muted"
        role="progressbar"
        aria-label="Companies found"
        aria-valuemin={0}
        aria-valuemax={s.requested_count}
        aria-valuenow={s.companies_found}
      >
        <span
          className={clsx(
            "absolute inset-y-0 left-0 rounded-full transition-[width] duration-700 ease-out",
            s.status === "failed" ? "bg-danger" : pct >= 100 ? "bg-success" : "bg-accent",
          )}
          style={{ width: `${Math.max(pct, running ? 2 : 0)}%` }}
        />
        {running && <span className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-white/50 to-transparent" style={{ animation: "loading-bar 1.4s ease-in-out infinite" }} aria-hidden />}
      </div>
      {s.connectors_total > 0 && (
        <div className="mt-3 flex items-center gap-2 text-xs text-fg-muted">
          <span className="flex gap-1" aria-hidden>
            {Array.from({ length: s.connectors_total }, (_, i) => (
              <span
                key={i}
                className={clsx(
                  "h-1.5 w-5 rounded-full transition-colors duration-500",
                  i < s.connectors_completed ? "bg-success" : running && i === s.connectors_completed ? "animate-pulse bg-accent/60" : "bg-border-strong",
                )}
              />
            ))}
          </span>
          <span className="tabular">
            {s.connectors_completed} of {s.connectors_total} sources checked
          </span>
        </div>
      )}
    </div>
  );
}

function SearchResults({ searchId, onRunning }: { searchId: string; onRunning: (running: boolean) => void }) {
  const search = useApi<LeadSearch>(`/lead-searches/${searchId}`);
  const results = useApi<Page<LeadSearchResult>>(`/lead-searches/${searchId}/results`, { page_size: 100 });
  const running = search.data?.status === "researching" || search.data?.status === "pending";
  const checking = search.data?.enrichment_status === "running";
  const { reload: reloadSearch } = search;
  const { reload: reloadResults } = results;

  // Discovery runs in the background: refresh progress and results (they appear one by one) until it finishes,
  // then more slowly while websites are still being checked.
  useEffect(() => {
    if (!running && !checking) return;
    const timer = setInterval(
      () => {
        void reloadSearch();
        void reloadResults();
      },
      running ? POLL_MS : ENRICH_POLL_MS,
    );
    return () => clearInterval(timer);
  }, [running, checking, reloadSearch, reloadResults]);
  // The form's radar spins while this search runs.
  useEffect(() => {
    onRunning(running);
    return () => onRunning(false);
  }, [running, onRunning]);

  if (search.error) return <ErrorState message={search.error.message} onRetry={search.reload} />;
  const s = search.data;
  if (!s) return null;
  const state = SEARCH_STATUS[s.status];

  return (
    <Section
      flush
      className="mt-6"
      title={
        <span className="flex items-center gap-2">
          Results
          <Badge tone={state.tone} dot live={running}>
            {state.label}
          </Badge>
        </span>
      }
      description={[s.message, !running && checking ? "Researching company websites…" : null].filter(Boolean).join(" · ") || undefined}
    >
      <SearchProgress s={s} newCount={results.data?.items.filter((r) => r.is_new).length ?? 0} />
      <DataTable
        caption="Search results"
        rows={results.data?.items}
        rowKey={(r) => r.company.id}
        error={results.error?.message}
        onRetry={results.reload}
        rowHref={(r) => `/companies/${r.company.id}`}
        empty={
          <EmptyState
            compact
            icon={<SearchX />}
            title={running ? "Searching sources…" : "No matching companies found"}
            description={running ? "Companies appear here as they are found." : undefined}
          />
        }
        columns={[
          {
            key: "company",
            header: "Company",
            cell: (r) => (
              <span className="flex items-center gap-2.5">
                <Avatar name={r.company.name} size="sm" domain={r.company.domain} />
                <span className="font-medium">{r.company.name}</span>
                {r.is_new && <Badge tone="accent">New</Badge>}
              </span>
            ),
          },
          { key: "industry", header: "Industry", cell: (r) => r.company.industry ?? "—" },
          { key: "place", header: "City / Region", cell: (r) => place(r.company.headquarters_city, r.company.headquarters_region) },
          {
            key: "website",
            header: "Website",
            cell: (r) => {
              const href = safeHref(r.company.website);
              if (!href) return <span className="text-fg-subtle">—</span>;
              return (
                <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                  {r.company.domain ?? new URL(href).hostname.replace(/^www\./, "")}
                  <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              );
            },
          },
          { key: "size", header: "Employees", align: "right", cell: (r) => r.company.employee_count_estimate?.toLocaleString() ?? "—" },
          {
            key: "confidence",
            header: "Confidence",
            cell: (r) => {
              const level = r.company.identity_confidence;
              return (
                <span className="inline-flex items-center gap-2" title={`${r.source_count} source${r.source_count === 1 ? "" : "s"}`}>
                  {level ? <Badge tone={CONFIDENCE[level].tone}>{CONFIDENCE[level].label}</Badge> : <span className="text-fg-subtle">—</span>}
                  <span className="text-xs text-fg-muted tabular">
                    {r.source_count} src
                  </span>
                </span>
              );
            },
          },
          { key: "status", header: "Status", cell: (r) => <Badge tone={COMPANY_STATUS[r.company.status].tone}>{COMPANY_STATUS[r.company.status].label}</Badge> },
        ]}
      />
    </Section>
  );
}

function FindLeads() {
  const router = useRouter();
  const searchId = useSearchParams().get("search");
  const [country, setCountry] = useState("Lebanon");
  const [region, setRegion] = useState("");
  const [industry, setIndustry] = useState("");
  const [offering, setOffering] = useState<Offering>("ANY");
  const [count, setCount] = useState("50");
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const offeringLabel = offering === "ANY" ? "" : `${OFFERINGS.find((o) => o.value === offering)?.label} `;
  const setup = `${country}|${region}|${industry}|${offering}|${count}`;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const search = await api<LeadSearch>("/lead-searches", {
        method: "POST",
        body: { country, city: region || null, industry: industry || null, solution: offering.toLowerCase(), requested_count: Number(count) },
      });
      router.replace(`/find-leads?search=${search.id}`, { scroll: false });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not start the search");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Find Leads" description="Find a specific company, or search for companies in a market." />
      <CompanySearch country={country} />
      <form onSubmit={submit} className="grid overflow-hidden rounded-xl border border-border bg-surface shadow-card lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-5 p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Country" htmlFor="fl-country" required>
              <Select id="fl-country" value={country} onChange={(e) => setCountry(e.target.value)} required className="w-full">
                {countryNames().map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="City / Region" htmlFor="fl-region">
              <Input id="fl-region" value={region} onChange={(e) => setRegion(e.target.value)} placeholder="All regions" className="w-full" />
            </Field>
          </div>

          <Field label="Industry" htmlFor="fl-industry">
            <Input
              id="fl-industry"
              list="fl-industry-list"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              placeholder="All industries"
              className="w-full"
            />
            <datalist id="fl-industry-list">
              {INDUSTRIES.map((i) => (
                <option key={i} value={i} />
              ))}
            </datalist>
          </Field>

          <div>
            <p className="mb-1.5 text-xs font-medium text-fg">What are you selling?</p>
            <FilterPills label="What are you selling?" options={OFFERINGS} value={offering} onChange={setOffering} />
          </div>

          <div>
            <p className="mb-1.5 text-xs font-medium text-fg">How many companies?</p>
            <div className="flex flex-wrap items-center gap-2">
              <FilterPills label="How many companies?" options={COUNT_PRESETS.map((v) => ({ value: v, label: v }))} value={count} onChange={setCount} />
              <span className="text-xs text-fg-subtle">or</span>
              <Input
                id="fl-count"
                aria-label="Custom number of companies"
                type="number"
                min={1}
                max={500}
                value={count}
                onChange={(e) => setCount(e.target.value)}
                required
                className="w-24 tabular"
              />
            </div>
          </div>

          <div className="border-t border-border pt-4">
            <Button type="submit" loading={busy} disabled={running}>
              <Search className="h-3.5 w-3.5" aria-hidden /> {running ? "Search running…" : "Find Leads"}
            </Button>
          </div>
        </div>

        {/* Read-back of the search being set up: the radar sweeps once per change and spins while a search runs. */}
        <aside className="flex flex-col items-center justify-center gap-4 bg-accent px-6 py-8 text-center text-white">
          <RadarScope scanning={busy || running} pulseKey={setup} blips={Math.round(Number(count) / 25)} className="max-w-[170px]" />
          <p key={setup} className="animate-page-in text-[13.5px] leading-relaxed text-white/85">
            {running ? "Searching for " : "Find "}
            <span className="font-display text-[22px] font-semibold tabular text-white">{Number(count) || 0}</span> {offeringLabel}prospects
            {industry && (
              <>
                {" "}in <span className="font-semibold text-white">{industry}</span>
              </>
            )}
            <br />
            {region ? `${region}, ` : ""}
            {country}
          </p>
        </aside>
      </form>
      {searchId && <SearchResults key={searchId} searchId={searchId} onRunning={setRunning} />}
    </>
  );
}

export default function FindLeadsPage() {
  return (
    <Suspense>
      <FindLeads />
    </Suspense>
  );
}
