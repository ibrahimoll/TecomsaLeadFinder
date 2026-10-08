"use client";

import clsx from "clsx";
import { Radar, Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { DiscoveryStatusBadge } from "@/components/status-badges";
import {
  Alert,
  Button,
  ConfirmDialog,
  DataTable,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Pagination,
  Section,
  Select,
  Skeleton,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { useUrlState } from "@/lib/use-url-state";
import type { DiscoveryOptions, DiscoveryRun, Page } from "@/types";

const CUSTOM = "__custom__";
const PAGE_SIZE = 20;

function SearchForm({ options }: { options: DiscoveryOptions }) {
  const router = useRouter();
  const [country, setCountry] = useState(options.countries[0]?.code ?? "LB");
  const [industry, setIndustry] = useState("food_manufacturing");
  const [custom, setCustom] = useState("");
  const [area, setArea] = useState("");
  const [count, setCount] = useState(100);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const areas = options.areas[country] ?? [];
  const countryName = options.countries.find((c) => c.code === country)?.name ?? country;
  const isCustom = industry === CUSTOM;

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
          industry: isCustom ? null : industry,
          custom_query: isCustom ? custom : null,
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
    <form onSubmit={submit} className="rounded-lg border border-border bg-surface shadow-[0_1px_0_rgb(17_17_20/0.03)]">
      <div className="grid grid-cols-1 gap-4 p-5 md:grid-cols-2 xl:grid-cols-[160px_minmax(0,1.3fr)_minmax(0,1fr)_auto]">
        <Field label="Country" htmlFor="d-country">
          <Select id="d-country" value={country} onChange={(e) => { setCountry(e.target.value); setArea(""); }}>
            {options.countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Industry" htmlFor="d-industry">
          {isCustom ? (
            <div className="flex gap-1.5">
              <Input
                id="d-industry"
                autoFocus
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                placeholder="e.g. Plastic packaging manufacturer"
                maxLength={200}
                required
              />
              <Button variant="ghost" className="px-2" onClick={() => { setIndustry("food_manufacturing"); setCustom(""); }} aria-label="Back to the industry list" title="Back to the list">
                <X className="h-3.5 w-3.5" aria-hidden />
              </Button>
            </div>
          ) : (
            <Select id="d-industry" value={industry} onChange={(e) => setIndustry(e.target.value)}>
              {options.industries.map((i) => (
                <option key={i.key} value={i.key}>
                  {i.label}
                </option>
              ))}
              <option value={CUSTOM}>Other / custom…</option>
            </Select>
          )}
        </Field>
        <Field label="City or region" htmlFor="d-area">
          <Select id="d-area" value={area} onChange={(e) => setArea(e.target.value)}>
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
        </Field>
        <Field label="Number of companies">
          <div className="inline-flex h-8 rounded-md border border-border-strong bg-surface-muted/60 p-0.5" role="radiogroup" aria-label="Number of companies">
            {options.counts.map((n) => (
              <button
                key={n}
                type="button"
                role="radio"
                aria-checked={count === n}
                onClick={() => setCount(n)}
                className={clsx(
                  "min-w-[44px] rounded-[5px] px-2.5 text-[13px] font-medium tabular transition-colors",
                  count === n ? "bg-surface text-fg shadow-[0_0_0_1px_rgb(var(--border)),0_1px_2px_rgb(17_17_20/0.06)]" : "text-fg-muted hover:text-fg",
                )}
              >
                {n}
              </button>
            ))}
          </div>
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-border bg-surface-muted/40 px-5 py-3">
        <p className="mr-auto text-xs text-fg-muted">
          Searches {options.sources.map((s) => s.label).join(" and ")}, then checks every company against LeadFinder and TECOMSA&apos;s Odoo
          data. Only new companies are added.
        </p>
        {error && <span className="w-full sm:w-auto"><Alert>{error}</Alert></span>}
        <Button type="submit" loading={busy} disabled={isCustom && !custom.trim()}>
          <Radar className="h-3.5 w-3.5" aria-hidden /> Find companies
        </Button>
      </div>
    </form>
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
        <Select aria-label="Whose searches" className="w-[150px]" value={f.mine} onChange={(e) => setF({ mine: e.target.value })}>
          <option value="">Everyone&apos;s searches</option>
          <option value="1">My searches</option>
        </Select>
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
        empty={<EmptyState compact icon={<Radar />} title="No searches yet" description="Run your first search above." />}
        columns={[
          {
            key: "query",
            header: "Search",
            cell: (r) => (
              <div className="leading-tight">
                <p className="font-medium">{r.query_label}</p>
                <p className="text-[11.5px] text-fg-subtle">Up to {r.requested_count} companies</p>
              </div>
            ),
          },
          { key: "status", header: "Status", cell: (r) => <DiscoveryStatusBadge status={r.status} /> },
          { key: "new", header: "New", align: "right", cell: (r) => <span className="font-medium">{r.new_company_count}</span> },
          { key: "protected", header: "Protected", align: "right", cell: (r) => r.odoo_protected_count },
          { key: "known", header: "Known", align: "right", cell: (r) => r.existing_company_count },
          { key: "examined", header: "Examined", align: "right", cell: (r) => <span className="text-fg-muted">{r.raw_results_count}</span> },
          { key: "by", header: "By", cell: (r) => <span className="text-fg-muted">{r.creator?.name ?? "—"}</span> },
          { key: "at", header: "Date", cell: (r) => <span className="text-fg-muted">{formatDateTime(r.created_at)}</span> },
          ...(isAdmin
            ? [
                {
                  key: "actions",
                  header: <span className="sr-only">Actions</span>,
                  align: "right" as const,
                  cell: (r: DiscoveryRun) => (
                    <Button
                      variant="ghost"
                      size="sm"
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
            <input type="checkbox" checked={withData} onChange={(e) => setWithData(e.target.checked)} className="mt-0.5 accent-[rgb(var(--ink))]" />
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
    <>
      <PageHeader
        title="Find companies"
        description="Discover companies TECOMSA can sell to from free public business data. Each one is checked against LeadFinder and TECOMSA's Odoo before it is added."
      />
      <div className="space-y-6">
        {options.error ? (
          <Alert title="The search options could not be loaded">{options.error.message}</Alert>
        ) : options.data ? (
          <SearchForm options={options.data} />
        ) : (
          <Skeleton className="h-[148px] w-full rounded-lg" />
        )}
        <History />
        <p className="text-[11.5px] text-fg-subtle">
          Place data © Overture Maps Foundation and contributors (CDLA Permissive 2.0 and other open licences) · © OpenStreetMap
          contributors (ODbL).
        </p>
      </div>
    </>
  );
}

export default function FindCompaniesPage() {
  return (
    <Suspense>
      <FindCompanies />
    </Suspense>
  );
}
