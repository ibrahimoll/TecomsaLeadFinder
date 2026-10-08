"use client";

import clsx from "clsx";
import { ArrowRight, Building2, Check, Globe2, Hash, MapPin, Radar, Sparkles, Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { Suspense, useMemo, useState, type FormEvent } from "react";

import { RadarScope } from "@/components/radar-scope";
import { DiscoveryStatusBadge } from "@/components/status-badges";
import {
  Alert,
  Button,
  ConfirmDialog,
  CountUp,
  DataTable,
  EmptyState,
  Field,
  Input,
  Pagination,
  Section,
  Select,
  Skeleton,
  TimeAgo,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { useUrlState } from "@/lib/use-url-state";
import type { DiscoveryOptions, DiscoveryRun, Page } from "@/types";

const PAGE_SIZE = 20;

type Industry = DiscoveryOptions["industries"][number];

/**
 * Searchable industry field over 2,000+ industries: the browser's own autocomplete (datalist)
 * filters as you type, featured industries are one-click chips, and any other text runs as a
 * custom keyword search.
 */
function IndustryPicker({
  industries,
  text,
  match,
  onText,
}: {
  industries: Industry[];
  text: string;
  match: Industry | undefined;
  onText: (text: string) => void;
}) {
  const featured = industries.filter((i) => i.group === "Featured");
  return (
    <div>
      <div className="relative">
        <Building2 className="pointer-events-none absolute left-3 top-1/2 z-10 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" aria-hidden />
        <Input
          id="d-industry"
          list="d-industry-list"
          className="pl-8 pr-8"
          value={text}
          onChange={(e) => onText(e.target.value)}
          placeholder={`Search ${industries.length.toLocaleString()} industries, or type your own`}
          maxLength={200}
          autoComplete="off"
          aria-describedby="d-industry-hint"
          required
        />
        {text && (
          <button
            type="button"
            onClick={() => onText("")}
            aria-label="Clear industry"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-fg-subtle transition-colors hover:bg-surface-hover hover:text-fg"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        )}
        <datalist id="d-industry-list">
          {industries.map((i) => (
            <option key={i.key} value={i.label} label={i.group} />
          ))}
        </datalist>
      </div>
      <p id="d-industry-hint" className="mt-1.5 flex min-h-[18px] items-center gap-1.5 text-xs" aria-live="polite">
        {match ? (
          <span key={match.key} className="inline-flex animate-pop-in items-center gap-1.5 text-success">
            <Check className="h-3 w-3" strokeWidth={3} aria-hidden />
            {match.group === "Featured" ? "Featured industry, tuned for TECOMSA" : `${match.group} category, including its subcategories`}
          </span>
        ) : text.trim() ? (
          <span className="inline-flex animate-pop-in items-center gap-1.5 text-fg-muted">
            <Sparkles className="h-3 w-3 text-accent" aria-hidden /> Custom search: these words are matched against company names and categories
          </span>
        ) : (
          <span className="text-fg-subtle">Start typing, e.g. bakery, law firm, solar, hospital…</span>
        )}
      </p>
      <div className="stagger mt-2.5 flex flex-wrap gap-1.5" aria-label="Featured industries">
        {featured.map((i) => {
          const active = match?.key === i.key;
          return (
            <button
              key={i.key}
              type="button"
              onClick={() => onText(i.label)}
              aria-pressed={active}
              className={clsx(
                "rounded-full border px-2.5 py-1 text-xs font-medium transition-[background-color,border-color,color,transform] duration-200 active:scale-95",
                active
                  ? "border-accent bg-accent text-white shadow-[0_2px_8px_-2px_rgb(var(--accent)/0.6)]"
                  : "border-border bg-surface text-fg-muted hover:border-accent/40 hover:text-accent",
              )}
            >
              {i.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Segmented choice with a pill that slides to the selected option. */
function CountPicker({ counts, value, onChange }: { counts: number[]; value: number; onChange: (n: number) => void }) {
  const index = Math.max(0, counts.indexOf(value));
  return (
    <div className="relative inline-flex h-9 rounded-md border border-border-strong bg-surface-muted p-0.5" role="radiogroup" aria-label="Number of companies">
      <span
        className="absolute bottom-0.5 top-0.5 w-12 rounded-[6px] bg-accent shadow-[0_2px_8px_-2px_rgb(var(--accent)/0.6)] transition-transform duration-300 ease-out"
        style={{ transform: `translateX(${index * 100}%)` }}
        aria-hidden
      />
      {counts.map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          onClick={() => onChange(n)}
          className={clsx(
            "relative z-10 w-12 rounded-[6px] text-[13px] font-semibold tabular transition-colors duration-300",
            value === n ? "text-white" : "text-fg-muted hover:text-fg",
          )}
        >
          {n}
        </button>
      ))}
    </div>
  );
}

function SearchForm({ options }: { options: DiscoveryOptions }) {
  const router = useRouter();
  const [country, setCountry] = useState(options.countries[0]?.code ?? "LB");
  const [industryText, setIndustryText] = useState(
    () => options.industries.find((i) => i.key === "food_manufacturing")?.label ?? options.industries[0]?.label ?? "",
  );
  const [area, setArea] = useState("");
  const [count, setCount] = useState(100);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const areas = options.areas[country] ?? [];
  const countryName = options.countries.find((c) => c.code === country)?.name ?? country;
  const byLabel = useMemo(() => new Map(options.industries.map((i) => [i.label.toLowerCase(), i])), [options.industries]);
  // An exact industry name selects that industry; anything else is a custom keyword search.
  const match = byLabel.get(industryText.trim().toLowerCase());
  const custom = match ? null : industryText.trim();
  const industryLabel = match?.label ?? (custom || "an industry");
  const areaLabel = area ? areas.find((a) => a.key === area)?.label ?? area : `all of ${countryName}`;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const run = await api<DiscoveryRun>("/discovery/runs", {
        method: "POST",
        body: {
          country,
          city: area || null,
          industry: match?.key ?? null,
          custom_query: custom,
          requested_count: count,
        },
      });
      router.push(`/discovery/${run.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The search could not be started.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="animate-page-in overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <div className="grid lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        {/* Brand panel: title, live radar and the search read back as a sentence. */}
        <div
          className="relative overflow-hidden px-6 py-7 text-white md:px-8"
          style={{
            background:
              "radial-gradient(120% 90% at 100% 0%, rgb(214 28 36) 0%, transparent 60%), linear-gradient(150deg, rgb(150 6 12) 0%, rgb(196 18 26) 55%, rgb(110 4 8) 100%)",
          }}
        >
          <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-white/70">Discovery</p>
          <h1 className="mt-1.5 text-[28px] font-semibold leading-9 tracking-[-0.02em] text-white">Find companies</h1>
          <p className="mt-1.5 max-w-sm text-[13.5px] leading-5 text-white/80">
            Scan free public business data. Every company is checked against LeadFinder and TECOMSA&apos;s Odoo before it is added.
          </p>
          <div className="mx-auto mt-6 hidden max-w-[200px] justify-center sm:flex lg:mt-8">
            <RadarScope scanning={busy} pulseKey={`${country}|${area}|${match?.key ?? "custom"}|${count}`} blips={Math.round(count / 25)} />
          </div>
        </div>

        {/* Controls */}
        <div className="flex flex-col">
          <div className="stagger grid flex-1 grid-cols-1 gap-5 p-6 md:grid-cols-2 md:p-7">
            <Field label="Country" htmlFor="d-country">
              <div className="relative">
                <Globe2 className="pointer-events-none absolute left-3 top-1/2 z-10 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" aria-hidden />
                <Select id="d-country" className="pl-8" value={country} onChange={(e) => { setCountry(e.target.value); setArea(""); }}>
                  {options.countries.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </div>
            </Field>
            <Field label="City or region" htmlFor="d-area">
              <div className="relative">
                <MapPin className="pointer-events-none absolute left-3 top-1/2 z-10 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" aria-hidden />
                <Select id="d-area" className="pl-8" value={area} onChange={(e) => setArea(e.target.value)}>
                  <option value="">All {countryName}</option>
                  <optgroup label="Cities">
                    {areas.filter((a) => a.kind === "city").map((a) => (
                      <option key={a.key} value={a.key}>
                        {a.label}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="Governorates">
                    {areas.filter((a) => a.kind === "governorate").map((a) => (
                      <option key={a.key} value={a.key}>
                        {a.label}
                      </option>
                    ))}
                  </optgroup>
                </Select>
              </div>
            </Field>
            <Field label="Industry" htmlFor="d-industry" className="md:col-span-2">
              <IndustryPicker industries={options.industries} text={industryText} match={match} onText={setIndustryText} />
            </Field>
            <Field label="Number of companies" className="md:col-span-2">
              <div className="flex flex-wrap items-center gap-3">
                <CountPicker counts={options.counts} value={count} onChange={setCount} />
                <span className="flex items-center gap-1 text-xs text-fg-subtle">
                  <Hash className="h-3 w-3" aria-hidden /> the most we will add from this search
                </span>
              </div>
            </Field>
          </div>

          {/* Read-back + action */}
          <div className="flex flex-wrap items-center gap-4 border-t border-border bg-surface-muted/50 px-6 py-4 md:px-7">
            <p className="mr-auto min-w-0 text-[13.5px] leading-5 text-fg-muted" aria-live="polite">
              Scan for{" "}
              <span key={industryLabel} className="inline-block animate-pop-in font-semibold text-fg">{industryLabel}</span> in{" "}
              <span key={areaLabel} className="inline-block animate-pop-in font-semibold text-fg">{areaLabel}</span>, up to{" "}
              <span key={count} className="inline-block animate-pop-in font-semibold tabular text-accent">{count}</span> new companies.
              <span className="mt-0.5 block text-xs text-fg-subtle">
                Sources: {options.sources.map((s) => s.label).join(" and ")}. Only companies new to TECOMSA are added.
              </span>
            </p>
            {error && <span className="w-full"><Alert>{error}</Alert></span>}
            <Button
              type="submit"
              loading={busy}
              disabled={!industryText.trim()}
              className="group h-11 px-5 text-[14px]"
            >
              <Radar className={clsx("h-4 w-4", busy && "animate-spin")} aria-hidden />
              {busy ? "Starting scan…" : "Find companies"}
              {!busy && <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden />}
            </Button>
          </div>
        </div>
      </div>
    </form>
  );
}

/** One run's outcome as a stacked bar: new / protected / already known, out of everything examined. */
function ResultMix({ run }: { run: DiscoveryRun }) {
  const total = Math.max(run.raw_results_count, run.new_company_count + run.odoo_protected_count + run.existing_company_count, 1);
  const parts = [
    { key: "new", value: run.new_company_count, cls: "bg-success" },
    { key: "protected", value: run.odoo_protected_count, cls: "bg-warning" },
    { key: "known", value: run.existing_company_count, cls: "bg-fg-subtle/50" },
  ];
  return (
    <div className="min-w-[180px]">
      <div
        className="flex h-1.5 overflow-hidden rounded-full bg-surface-muted"
        role="img"
        aria-label={`${run.new_company_count} new, ${run.odoo_protected_count} protected, ${run.existing_company_count} already in LeadFinder, of ${run.raw_results_count} examined`}
      >
        {parts.map((p) =>
          p.value ? <span key={p.key} className={clsx("h-full origin-left animate-grow-x", p.cls)} style={{ width: `${(p.value / total) * 100}%` }} /> : null,
        )}
      </div>
      <p className="mt-1 text-[11.5px] text-fg-muted">
        <span className="font-medium text-warning">{run.odoo_protected_count}</span> protected ·{" "}
        <span className="font-medium text-fg">{run.existing_company_count}</span> known · {run.raw_results_count} examined
      </p>
    </div>
  );
}

function History() {
  const user = useCurrentUser();
  const [f, setF] = useUrlState(["page", "mine"] as const);
  const page = Number(f.page) || 1;
  const runs = useApi<Page<DiscoveryRun>>("/discovery/runs", { page, page_size: PAGE_SIZE, mine: f.mine === "1" || undefined });
  const [target, setTarget] = useState<DiscoveryRun | null>(null);
  const [withData, setWithData] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = user.role === "ADMIN";

  async function remove() {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ companies_removed: number; companies_kept: number }>(`/discovery/runs/${target.id}`, {
        method: "DELETE",
        query: { with_data: withData },
      });
      setNotice(
        `Deleted “${target.query_label}”.` +
          (withData ? ` Removed ${r.companies_removed} companies; ${r.companies_kept} kept because they are still in use.` : " Its companies were kept."),
      );
      setTarget(null);
      runs.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The search could not be deleted.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      title="Search history"
      description="Open a search to see every company it examined and why it was or was not added."
      flush
      actions={
        isPrivileged(user) && (
          <Select aria-label="Whose searches" className="w-[190px]" value={f.mine} onChange={(e) => setF({ mine: e.target.value })}>
            <option value="">Everyone&apos;s searches</option>
            <option value="1">My searches</option>
          </Select>
        )
      }
    >
      {notice && (
        <div className="border-b border-border px-4 py-2.5">
          <Alert tone="success">{notice}</Alert>
        </div>
      )}
      <DataTable<DiscoveryRun, number>
        caption="Search history"
        rows={runs.data?.items}
        loading={runs.loading}
        error={runs.error?.message}
        onRetry={runs.reload}
        rowKey={(r) => r.id}
        rowHref={(r) => `/discovery/${r.id}`}
        empty={<EmptyState compact icon={<Radar />} title="No searches yet" description="Run your first scan above." />}
        columns={[
          {
            key: "query",
            header: "Search",
            cell: (r) => (
              <div>
                <div className="min-w-0 leading-tight">
                  <p className="truncate font-medium transition-colors group-hover:text-accent">{r.query_label}</p>
                  <p className="text-[11.5px] text-fg-subtle">Up to {r.requested_count} companies</p>
                </div>
              </div>
            ),
          },
          { key: "status", header: "Status", cell: (r) => <DiscoveryStatusBadge status={r.status} /> },
          {
            key: "new",
            header: "New",
            align: "right",
            cell: (r) => (
              <span
                className={clsx(
                  "inline-flex min-w-[44px] justify-center rounded-full px-2 py-0.5 font-display text-[13px] font-semibold tabular",
                  r.new_company_count ? "bg-success-soft text-success" : "bg-surface-muted text-fg-muted",
                )}
              >
                {r.new_company_count ? "+" : ""}
                <CountUp value={r.new_company_count} reveal={`run:${r.id}`} />
              </span>
            ),
          },
          { key: "mix", header: "Result mix", cell: (r) => <ResultMix run={r} /> },
          { key: "by", header: "By", cell: (r) => <span className="text-fg-muted">{r.creator?.name ?? "—"}</span> },
          { key: "at", header: "When", cell: (r) => <span className="text-fg-muted"><TimeAgo value={r.created_at} /></span> },
          ...(isAdmin
            ? [
                {
                  key: "actions",
                  header: <span className="sr-only">Actions</span>,
                  align: "right" as const,
                  cell: (r: DiscoveryRun) => (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="hover:!text-danger"
                      aria-label={`Delete search ${r.query_label}`}
                      title="Delete search"
                      onClick={() => {
                        setNotice(null);
                        setWithData(false);
                        setTarget(r);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />
      {runs.data && (
        <div className="border-t border-border">
          <Pagination page={page} pageSize={PAGE_SIZE} total={runs.data.total} onPage={(p) => setF({ page: String(p) })} />
        </div>
      )}
      <ConfirmDialog
        open={target !== null}
        title="Delete this search?"
        tone="danger"
        confirmLabel={withData ? "Delete search and companies" : "Delete search"}
        busy={busy}
        onConfirm={remove}
        onClose={() => setTarget(null)}
      >
        <div className="space-y-3 text-fg">
          <p className="text-fg-muted">“{target?.query_label}” and its result history will be removed.</p>
          <label className="flex cursor-pointer gap-2.5 rounded border border-border px-3 py-2.5">
            <input type="checkbox" checked={withData} onChange={(e) => setWithData(e.target.checked)} className="mt-0.5 accent-[rgb(var(--accent))]" />
            <span>
              <span className="block font-medium">Also delete the companies it added</span>
              <span className="block text-xs text-fg-muted">
                Only companies no other search found and that are not used in a campaign, with contacts, notes or Odoo links.
              </span>
            </span>
          </label>
          {error && <Alert>{error}</Alert>}
        </div>
      </ConfirmDialog>
    </Section>
  );
}

function FindCompanies() {
  const options = useApi<DiscoveryOptions>("/discovery/options");
  return (
    <div className="space-y-6">
      {options.error ? (
        <Alert title="The search options could not be loaded">{options.error.message}</Alert>
      ) : options.data ? (
        <SearchForm options={options.data} />
      ) : (
        <Skeleton className="h-[360px] w-full rounded-xl" />
      )}
      <History />
      <p className="text-[11.5px] text-fg-subtle">
        Place data © Overture Maps Foundation and contributors (CDLA Permissive 2.0 and other open licences) · © OpenStreetMap
        contributors (ODbL).
      </p>
    </div>
  );
}

export default function FindCompaniesPage() {
  return (
    <Suspense>
      <FindCompanies />
    </Suspense>
  );
}
