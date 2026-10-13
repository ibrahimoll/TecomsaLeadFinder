"use client";

import { Building2, Download, FilterX, List, Map as MapIcon, Trash2 } from "lucide-react";
import dynamic from "next/dynamic";
import { Suspense, useEffect, useState } from "react";

import { Avatar, Badge, Button, Checkbox, ConfirmDialog, CountUp, DataTable, EmptyState, ErrorState, Input, PageHeader, Pagination, SearchInput, Section, Select, SelectionBar, Skeleton, Toolbar, toast } from "@/components/ui";
import { ScoutScore } from "@/components/agent-insights";
import { CompanyDeleteNote } from "@/components/company-delete-note";
import { PublicLookup } from "@/components/company-search";
import type { MapPin } from "@/components/companies-map";
import { OwnerSelect, useUsers } from "@/components/owner-select";
import { api, ApiError, useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { COMPANY_STATUS, COMPANY_STATUSES, displayName, place } from "@/lib/companies";
import { useDebouncedSearch, useUrlState } from "@/lib/use-url-state";
import type { Page } from "@/types";
import type { Company, CompanyStatus } from "@/types/v2";

const PAGE_SIZE = 50;
const KEYS = ["q", "status", "country", "region", "city", "industry", "owner", "mobile", "fit", "sort", "page", "view"] as const;
// Leaflet needs window: client only.
const CompaniesMap = dynamic(() => import("@/components/companies-map"), { ssr: false, loading: () => <Skeleton className="h-[560px] w-full" /> });
const FIT_TONE = { high: "success", medium: "info", low: "neutral", unknown: "neutral" } as const;
/** One-click work lists: the filters they set (the toolbar shows and refines them). */
const VIEWS: { key: string; label: string; hint: string; set: { fit: string; mobile: string } }[] = [
  { key: "all", label: "All companies", hint: "Everything, best fit first", set: { fit: "", mobile: "" } },
  { key: "call", label: "📱 Ready to call", hint: "A mobile or WhatsApp is known", set: { fit: "", mobile: "true" } },
  { key: "odoo", label: "Odoo prospects", hint: "Good fit for Odoo, with a mobile", set: { fit: "odoo", mobile: "true" } },
  { key: "frinzo", label: "Frinzo prospects", hint: "Good fit for Frinzo, with a mobile", set: { fit: "frinzo", mobile: "true" } },
  { key: "it", label: "IT prospects", hint: "Good fit for IT, with a mobile", set: { fit: "it", mobile: "true" } },
];
const SOLUTION_SHORT = { odoo: "Odoo", frinzo: "Frinzo", it: "IT" } as const;

function CompaniesView() {
  const [filters, setFilters] = useUrlState(KEYS);
  const [search, setSearch] = useDebouncedSearch(filters.q, (q) => setFilters({ q }));
  const page = Number(filters.page) || 1;
  const mapView = filters.view === "map";
  const query = {
    q: filters.q,
    status: filters.status,
    country: filters.country,
    region: filters.region,
    city: filters.city,
    industry: filters.industry,
    owner_id: filters.owner,
    has_mobile: filters.mobile || undefined,
    fit: filters.fit || undefined,
    sort: filters.sort === "name" ? "name" : "fit", // the best prospects first unless the user sorts by name
  };
  const { data, error, loading, reload } = useApi<Page<Company>>(mapView ? null : "/companies", { ...query, page, page_size: PAGE_SIZE });
  const map = useApi<{ items: MapPin[]; unlocated: number; total: number; truncated: boolean }>(mapView ? "/companies/map" : null, query);
  const filtered = KEYS.some((k) => k !== "page" && k !== "view" && filters[k]);
  // The same filters as the list, as a CSV for Excel (one row per person, with their numbers).
  const exportUrl = `/api/companies/export.csv?${new URLSearchParams(
    Object.entries({ q: filters.q, status: filters.status, country: filters.country, region: filters.region, city: filters.city, industry: filters.industry, owner_id: filters.owner, has_mobile: filters.mobile, fit: filters.fit, sort: filters.sort === "name" ? "name" : "fit" }).filter((e): e is [string, string] => !!e[1]),
  )}`;
  const user = useCurrentUser();
  const users = useUsers(isPrivileged(user));
  const ownerName = new Map(users.map((u) => [u.id, u.name]));
  const [deleting, setDeleting] = useState<Company | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [confirmBulk, setConfirmBulk] = useState(false);
  const canDelete = isPrivileged(user);
  // Only delete what is on screen: a filter or page change drops the selection.
  const view = KEYS.map((k) => filters[k]).join("|");
  useEffect(() => setSelected(new Set()), [view]);

  async function changeStatus(company: Company, status: CompanyStatus) {
    try {
      await api(`/companies/${company.id}/status`, { method: "PATCH", body: { status } });
      toast.success(`${company.name}: ${COMPANY_STATUS[status].label}`);
      await reload();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not change the status");
    }
  }

  async function remove() {
    if (!deleting) return;
    setBusy(true);
    try {
      await api(`/companies/${deleting.id}`, { method: "DELETE" });
      toast.success(`${deleting.name} deleted`);
      setDeleting(null);
      await reload();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not delete the company");
    } finally {
      setBusy(false);
    }
  }

  async function archiveSelected() {
    const ids = [...selected];
    setBusy(true);
    const results = await Promise.allSettled(ids.map((id) => api(`/companies/${id}/status`, { method: "PATCH", body: { status: "archived" } })));
    const done = results.filter((r) => r.status === "fulfilled").length;
    if (done) toast.success(`${done} compan${done === 1 ? "y" : "ies"} archived`);
    if (done < ids.length) toast.error(`${ids.length - done} could not be archived`);
    setSelected(new Set());
    setConfirmBulk(false);
    setBusy(false);
    await reload();
  }

  // ponytail: one DELETE per company (no bulk endpoint); fine for a page of 50, add a bulk route if selections grow.
  async function removeSelected() {
    const ids = [...selected];
    setBusy(true);
    const results = await Promise.allSettled(ids.map((id) => api(`/companies/${id}`, { method: "DELETE" })));
    const failed = new Set(ids.filter((_, i) => results[i].status === "rejected"));
    const done = ids.length - failed.size;
    if (done) toast.success(`${done} compan${done === 1 ? "y" : "ies"} deleted`);
    if (failed.size) toast.error(`${failed.size} could not be deleted; they are still selected`);
    setSelected(failed);
    setConfirmBulk(false);
    setBusy(false);
    await reload();
  }

  return (
    <>
      <PageHeader
        title="Companies"
        actions={
          <a href={exportUrl} download className="inline-flex items-center gap-1.5 rounded border border-border-strong px-3 py-1.5 text-[12.5px] font-medium text-fg hover:bg-surface-hover">
            <Download className="h-3.5 w-3.5" aria-hidden /> Export to Excel
          </a>
        }
        description={
          <>
            {canDelete ? "Every lead generator's companies" : "Your companies: the ones you found first"}
            {(mapView ? map.data : data) && (
              <>
                {" · "}
                <span className="font-medium tabular text-fg">
                  <CountUp value={(mapView ? map.data : data)!.total} reveal="companies:total" />
                </span>{" "}
                {filtered ? "match" : "in total"}
              </>
            )}
          </>
        }
      />
      <Section flush>
        <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-4 py-2.5" role="group" aria-label="Views">
          {VIEWS.map((v) => {
            const on = Object.entries(v.set).every(([k, val]) => filters[k as (typeof KEYS)[number]] === val) && (v.key !== "all" || !filters.fit && !filters.mobile);
            return (
              <Button key={v.key} size="sm" variant={on ? "primary" : "secondary"} aria-pressed={on} onClick={() => setFilters({ ...v.set, page: "" })} title={v.hint}>
                {v.label}
              </Button>
            );
          })}
          <div className="ml-auto flex gap-1" role="group" aria-label="Display">
            <Button size="sm" variant={mapView ? "secondary" : "primary"} aria-pressed={!mapView} onClick={() => setFilters({ view: "" })}>
              <List className="h-3.5 w-3.5" aria-hidden /> List
            </Button>
            <Button size="sm" variant={mapView ? "primary" : "secondary"} aria-pressed={mapView} onClick={() => setFilters({ view: "map" })}>
              <MapIcon className="h-3.5 w-3.5" aria-hidden /> Map
            </Button>
          </div>
        </div>
        <Toolbar>
          <SearchInput value={search} onChange={setSearch} placeholder="Search name, domain or industry" className="w-72" label="Search companies" />
          <Select aria-label="Status" value={filters.status} onChange={(e) => setFilters({ status: e.target.value })} className="w-44">
            <option value="">All statuses</option>
            {COMPANY_STATUSES.map((s) => (
              <option key={s} value={s}>
                {COMPANY_STATUS[s].label}
              </option>
            ))}
          </Select>
          {canDelete && <OwnerSelect users={users} value={filters.owner} onChange={(owner) => setFilters({ owner })} allLabel="All lead generators" className="w-48" />}
          <Select aria-label="Fit" value={filters.fit} onChange={(e) => setFilters({ fit: e.target.value, page: "" })} className="w-44">
            <option value="">Any fit</option>
            <option value="odoo">Good fit for Odoo</option>
            <option value="frinzo">Good fit for Frinzo</option>
            <option value="it">Good fit for IT</option>
          </Select>
          <Checkbox label="📱 Has mobile" checked={filters.mobile === "true"} onChange={(e) => setFilters({ mobile: e.target.checked ? "true" : "", page: "" })} />
          <Select aria-label="Sort" value={filters.sort} onChange={(e) => setFilters({ sort: e.target.value, page: "" })} className="w-40">
            <option value="">Sort: best fit</option>
            <option value="name">Sort: name</option>
          </Select>
          {filtered && (
            <Button
              variant="ghost"
              size="sm"
              className="animate-pop-in"
              onClick={() => setFilters({ q: "", status: "", country: "", region: "", city: "", industry: "", owner: "", mobile: "", fit: "", sort: "", page: "" })}
            >
              <FilterX className="h-3.5 w-3.5" aria-hidden /> Clear filters
            </Button>
          )}
        </Toolbar>
        {mapView ? (
          map.error ? (
            <ErrorState message={map.error.message} onRetry={map.reload} />
          ) : (
            <>
              <p className="border-b border-border px-4 py-2 text-xs text-fg-muted">
                {map.data ? (
                  <>
                    <span className="font-medium tabular text-fg">{map.data.items.length}</span> compan{map.data.items.length === 1 ? "y" : "ies"} on the map ·{" "}
                    <span className="tabular">{map.data.unlocated}</span> without a location
                    {map.data.truncated && ` · only the first ${map.data.items.length + map.data.unlocated} of ${map.data.total} are mapped; narrow the filters`}
                  </>
                ) : (
                  "Loading the map…"
                )}
                {" · "}
                <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-success" /> High fit</span>{" "}
                <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-info" /> Medium fit</span>{" "}
                <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-fg-subtle" /> No fit yet</span>
              </p>
              <CompaniesMap pins={map.data?.items ?? []} />
            </>
          )
        ) : (
        <>
        <DataTable
          caption="Companies"
          rows={data?.items}
          rowKey={(c) => c.id}
          loading={loading}
          error={error?.message}
          onRetry={reload}
          rowHref={(c) => `/companies/${c.id}`}
          selection={canDelete ? { selected, onChange: setSelected } : undefined}
          empty={
            filters.q.trim().length >= 2 ? (
              <EmptyState
                icon={<Building2 />}
                title={`“${filters.q.trim()}” is not in LeadFinder yet`}
                description="Search the permitted public sources for it: a verified match is added and opened."
                action={<PublicLookup q={filters.q.trim()} country={filters.country || "Lebanon"} />}
              />
            ) : (
              <EmptyState
                icon={<Building2 />}
                title={filtered ? "No companies match these filters" : "No companies yet"}
                description={filtered ? undefined : "Companies found through Find Leads appear here automatically."}
              />
            )
          }
          columns={[
            {
              key: "name",
              header: "Company",
              cell: (c) => (
                <div className="flex min-w-0 items-center gap-2.5">
                  <Avatar name={displayName(c.name)} size="md" domain={c.own_domain === undefined ? c.domain : c.own_domain} />
                  <div className="min-w-0">
                    <p className="truncate font-medium" title={c.name}>
                      {displayName(c.name)}
                    </p>
                    {c.brief ? (
                      <p className="max-w-[380px] truncate text-xs text-fg-muted" title={c.brief}>
                        {c.brief}
                      </p>
                    ) : (
                      (c.own_domain === undefined ? c.domain : c.own_domain) && <p className="truncate text-xs text-fg-muted">{c.own_domain === undefined ? c.domain : c.own_domain}</p>
                    )}
                  </div>
                </div>
              ),
            },
            ...(data?.items.some((c) => c.scout_score != null)
              ? [{ key: "scout", header: "Scout", cell: (c: Company) => (c.scout_score != null ? <ScoutScore score={c.scout_score} reasons={c.scout_reasons} size="sm" /> : null) }]
              : []),
            {
              key: "industry",
              header: "Industry",
              // the directory's own activity ("Cosmetics industry/trading") says more than a generic "Other"
              cell: (c) => {
                const main = c.industry && c.industry !== "Other" ? c.industry : null;
                return main || c.sub_industry ? (
                  <span className="block max-w-[220px] truncate" title={[c.industry, c.sub_industry].filter(Boolean).join(" · ")}>
                    {main ?? c.sub_industry}
                    {main && c.sub_industry && <span className="block truncate text-xs text-fg-subtle">{c.sub_industry}</span>}
                  </span>
                ) : (
                  <span className="text-fg-subtle">—</span>
                );
              },
            },
            {
              key: "fit",
              header: "Best fit",
              cell: (c) => {
                const best = [...(c.fit ?? [])].filter((f) => f.fit_level === "high" || f.fit_level === "medium").sort((a, b) => b.points - a.points);
                return best.length ? (
                  <span className="flex items-center gap-1 whitespace-nowrap" title={best.map((f) => `${f.label}: ${f.fit_level} (${f.points} pts)`).join("\n")}>
                    <Badge tone={FIT_TONE[best[0].fit_level]}>
                      {SOLUTION_SHORT[best[0].solution]} · {best[0].fit_level === "high" ? "High" : "Med"}
                    </Badge>
                    {best.length > 1 && <span className="text-[11px] text-fg-subtle">+{best.length - 1}</span>}
                  </span>
                ) : (
                  <span className="text-fg-subtle">—</span>
                );
              },
            },
            {
              key: "location",
              header: "Location",
              cell: (c) =>
                c.headquarters_city || c.headquarters_region ? (
                  <span className="block max-w-[150px] truncate" title={place(c.headquarters_city, c.headquarters_region, c.headquarters_country)}>
                    {place(c.headquarters_city, c.headquarters_region)}
                  </span>
                ) : (
                  <span className="text-fg-subtle">{c.headquarters_country ?? "—"}</span>
                ),
            },
            // only when the page mixes lead generators (otherwise it is the same name on every row)
            ...(canDelete && new Set((data?.items ?? []).map((c) => c.owner_user_id)).size > 1
              ? [{ key: "owner", header: "Lead generator", cell: (c: Company) => (c.owner_user_id && ownerName.get(c.owner_user_id)) || <span className="text-fg-subtle">—</span> }]
              : []),
            {
              key: "status",
              header: "Status",
              cell: (c) => (
                <Select aria-label={`Status of ${c.name}`} value={c.status} onChange={(e) => changeStatus(c, e.target.value as CompanyStatus)} className="h-8 w-[118px] text-[12px]">
                  {COMPANY_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {COMPANY_STATUS[s].label}
                    </option>
                  ))}
                </Select>
              ),
            },
            ...(canDelete
              ? [
                  {
                    key: "delete",
                    header: "",
                    align: "right" as const,
                    cell: (c: Company) => (
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete ${c.name}`}
                        className="opacity-40 transition-opacity hover:text-danger focus-visible:opacity-100 group-hover:opacity-100"
                        onClick={() => setDeleting(c)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    ),
                  },
                ]
              : []),
          ]}
        />
        {data && data.total > 0 && (
          <div className="border-t border-border">
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={(p) => setFilters({ page: String(p) })} />
          </div>
        )}
        </>
        )}
      </Section>
      <SelectionBar count={selected.size} onClear={() => setSelected(new Set())}>
        <Button variant="ghost" size="sm" onClick={() => setConfirmBulk(true)}>
          <Trash2 className="h-3.5 w-3.5" aria-hidden /> Delete
        </Button>
      </SelectionBar>
      <ConfirmDialog
        open={confirmBulk}
        title={`Delete ${selected.size} compan${selected.size === 1 ? "y" : "ies"}?`}
        confirmLabel={`Delete ${selected.size}`}
        tone="danger"
        busy={busy}
        onConfirm={removeSelected}
        onClose={() => setConfirmBulk(false)}
        alternative={{ label: `Archive ${selected.size}`, onClick: () => void archiveSelected() }}
      >
        <CompanyDeleteNote count={selected.size} />
      </ConfirmDialog>
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting ? displayName(deleting.name) : "company"}?`}
        confirmLabel="Delete company"
        tone="danger"
        busy={busy}
        onConfirm={remove}
        onClose={() => setDeleting(null)}
        alternative={{
          label: "Archive instead",
          onClick: () => {
            if (deleting) void changeStatus(deleting, "archived");
            setDeleting(null);
          },
        }}
      >
        <CompanyDeleteNote />
      </ConfirmDialog>
    </>
  );
}


export default function CompaniesPage() {
  return (
    <Suspense>
      <CompaniesView />
    </Suspense>
  );
}
