"use client";

import { Building2, FilterX, Trash2 } from "lucide-react";
import { Suspense, useEffect, useState } from "react";

import { Avatar, Button, ConfirmDialog, CountUp, DataTable, EmptyState, Input, PageHeader, Pagination, SearchInput, Section, Select, SelectionBar, Toolbar, toast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { COMPANY_STATUS, COMPANY_STATUSES, place } from "@/lib/companies";
import { useDebouncedSearch, useUrlState } from "@/lib/use-url-state";
import type { Page } from "@/types";
import type { Company, CompanyStatus } from "@/types/v2";

const PAGE_SIZE = 50;
const KEYS = ["q", "status", "country", "region", "city", "industry", "page"] as const;

function CompaniesView() {
  const [filters, setFilters] = useUrlState(KEYS);
  const [search, setSearch] = useDebouncedSearch(filters.q, (q) => setFilters({ q }));
  const page = Number(filters.page) || 1;
  const { data, error, loading, reload } = useApi<Page<Company>>("/companies", {
    q: filters.q,
    status: filters.status,
    country: filters.country,
    region: filters.region,
    city: filters.city,
    industry: filters.industry,
    page,
    page_size: PAGE_SIZE,
  });
  const filtered = KEYS.some((k) => k !== "page" && filters[k]);
  const user = useCurrentUser();
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
        description={
          <>
            Every company LeadFinder knows, from all searches
            {data && (
              <>
                {" · "}
                <span className="font-medium tabular text-fg">
                  <CountUp value={data.total} reveal="companies:total" />
                </span>{" "}
                {filtered ? "match" : "in total"}
              </>
            )}
          </>
        }
      />
      <Section flush>
        <Toolbar>
          <SearchInput value={search} onChange={setSearch} placeholder="Search by name or domain" className="w-64" label="Search companies" />
          <FilterInput label="Country" value={filters.country} onCommit={(country) => setFilters({ country })} />
          <FilterInput label="Region" value={filters.region} onCommit={(region) => setFilters({ region })} />
          <FilterInput label="City" value={filters.city} onCommit={(city) => setFilters({ city })} />
          <FilterInput label="Industry" value={filters.industry} onCommit={(industry) => setFilters({ industry })} />
          <Select aria-label="Status" value={filters.status} onChange={(e) => setFilters({ status: e.target.value })} className="w-44">
            <option value="">All statuses</option>
            {COMPANY_STATUSES.map((s) => (
              <option key={s} value={s}>
                {COMPANY_STATUS[s].label}
              </option>
            ))}
          </Select>
          {filtered && (
            <Button
              variant="ghost"
              size="sm"
              className="animate-pop-in"
              onClick={() => setFilters({ q: "", status: "", country: "", region: "", city: "", industry: "", page: "" })}
            >
              <FilterX className="h-3.5 w-3.5" aria-hidden /> Clear filters
            </Button>
          )}
        </Toolbar>
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
            <EmptyState
              icon={<Building2 />}
              title={filtered ? "No companies match these filters" : "No companies yet"}
              description={filtered ? undefined : "Companies found through Find Leads appear here automatically."}
            />
          }
          columns={[
            {
              key: "name",
              header: "Company",
              cell: (c) => (
                <div className="flex min-w-0 items-center gap-2.5">
                  <Avatar name={c.name} size="md" domain={c.domain} />
                  <div className="min-w-0">
                    <p className="truncate font-medium">{c.name}</p>
                    {c.domain && <p className="truncate text-xs text-fg-muted">{c.domain}</p>}
                  </div>
                </div>
              ),
            },
            { key: "industry", header: "Industry", cell: (c) => c.industry ?? <span className="text-fg-subtle">—</span> },
            { key: "location", header: "Location", cell: (c) => place(c.headquarters_city, c.headquarters_region, c.headquarters_country) },
            { key: "size", header: "Employees", align: "right", cell: (c) => (c.employee_count_estimate ? c.employee_count_estimate.toLocaleString() : "—") },
            {
              key: "status",
              header: "Status",
              cell: (c) => (
                <Select aria-label={`Status of ${c.name}`} value={c.status} onChange={(e) => changeStatus(c, e.target.value as CompanyStatus)} className="h-8 w-44 text-[12.5px]">
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
      >
        Removes these companies, their locations and search results; Find Leads will not add them again. People and
        source records are kept. To only hide them, set their status to Archived.
      </ConfirmDialog>
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.name ?? "company"}?`}
        confirmLabel="Delete company"
        tone="danger"
        busy={busy}
        onConfirm={remove}
        onClose={() => setDeleting(null)}
      >
        Removes the company, its locations and search results; Find Leads will not add it again. People and
        source records are kept. To only hide it, set its status to Archived.
      </ConfirmDialog>
    </>
  );
}

/** Text filter committed to the URL as you type (debounced). */
function FilterInput({ label, value, onCommit }: { label: string; value: string; onCommit: (value: string) => void }) {
  const [text, setText] = useDebouncedSearch(value, onCommit);
  return <Input aria-label={label} placeholder={label} value={text} onChange={(e) => setText(e.target.value)} className="w-36" />;
}

export default function CompaniesPage() {
  return (
    <Suspense>
      <CompaniesView />
    </Suspense>
  );
}
