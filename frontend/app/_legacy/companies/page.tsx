"use client";

import { Bookmark, BookmarkPlus, Building2, Download, Megaphone, Plus, Search, Upload, UserSearch, X } from "lucide-react";
import { Suspense, useCallback, useEffect, useState } from "react";

import { CrmStatusBadge } from "@/components/status-badges";
import {
  Alert,
  Avatar,
  Badge,
  Button,
  ButtonLink,
  Checkbox,
  ConfirmDialog,
  DataTable,
  EmptyState,
  Field,
  PageHeader,
  Pagination,
  RowLink,
  SearchInput,
  Section,
  Select,
  SelectionBar,
  Toolbar,
  toast,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { countryNames, ODOO_STATUS_LABEL, ODOO_STATUSES, SOURCE_LABEL } from "@/lib/constants";
import { downloadCsv } from "@/lib/csv";
import { dash, formatDate, location } from "@/lib/format";
import { useDebouncedSearch, useUrlState } from "@/lib/use-url-state";
import type { Campaign, Company, CompanySource, OdooStatus, Page, ResearchStartResult } from "@/types";

const PAGE_SIZE = 50;
const KEYS = ["q", "crm_status", "protected", "source", "country", "sort", "page"] as const;
type FilterKey = "protected" | "crm_status" | "source" | "country";

/** Human-readable active filters, shown as removable tokens (Linear-style filter bar). */
function filterTokens(f: Record<(typeof KEYS)[number], string>): { key: FilterKey; field: string; value: string }[] {
  const tokens: { key: FilterKey; field: string; value: string }[] = [];
  if (f.protected) tokens.push({ key: "protected", field: "Protected or not", value: f.protected === "true" ? "Protected" : "Not protected" });
  if (f.crm_status) tokens.push({ key: "crm_status", field: "Odoo status", value: ODOO_STATUS_LABEL[f.crm_status as OdooStatus] ?? f.crm_status });
  if (f.source) tokens.push({ key: "source", field: "Source", value: SOURCE_LABEL[f.source as CompanySource] ?? f.source });
  if (f.country) tokens.push({ key: "country", field: "Country", value: f.country });
  return tokens;
}

function exportCompanies(companies: Company[]) {
  downloadCsv(
    `leadfinder-companies-${new Date().toISOString().slice(0, 10)}.csv`,
    ["Company", "Website", "Phone", "Email", "City", "Country", "Industry", "Relationship", "Source", "Owner"],
    companies.map((c) => [
      c.name, c.website, c.main_phone, c.main_email, c.city, c.country, c.industry,
      ODOO_STATUS_LABEL[c.odoo_status], c.source_label, c.salesperson?.name,
    ]),
  );
}

function AddToCampaignDialog({ companies, onClose, onDone }: { companies: Company[]; onClose: () => void; onDone: (msg: string) => void }) {
  const campaigns = useApi<Page<Campaign>>(companies.length ? "/campaigns" : null, { page_size: 100 });
  const open = (campaigns.data?.items ?? []).filter((c) => c.status === "DRAFT" || c.status === "READY");
  const [campaignId, setCampaignId] = useState("");
  const [includeProtected, setIncludeProtected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const protectedCount = companies.filter((c) => c.is_protected).length;
  const targets = includeProtected ? companies : companies.filter((c) => !c.is_protected);

  async function add() {
    setBusy(true);
    setError(null);
    let added = 0;
    let already = 0;
    try {
      for (const company of targets) {
        try {
          await api(`/campaigns/${campaignId}/companies/${company.id}`, { method: "POST" });
          added += 1;
        } catch (err) {
          if (err instanceof ApiError && err.status === 409) already += 1;
          else throw err;
        }
      }
      const name = open.find((c) => String(c.id) === campaignId)?.name ?? "the campaign";
      onDone(
        `Added ${added} ${added === 1 ? "company" : "companies"} to ${name}` +
          (already ? `; ${already} already there` : "") +
          (!includeProtected && protectedCount ? `; ${protectedCount} protected skipped` : "") + ".",
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add the companies.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ConfirmDialog
      open={companies.length > 0}
      title={`Add ${companies.length} ${companies.length === 1 ? "company" : "companies"} to a campaign`}
      confirmLabel={`Add ${targets.length}`}
      busy={busy}
      confirmDisabled={!campaignId || targets.length === 0}
      onConfirm={add}
      onClose={onClose}
    >
      <div className="space-y-3 text-fg">
        {error && <Alert>{error}</Alert>}
        <Field label="Campaign" htmlFor="bulk-campaign" hint={open.length === 0 && !campaigns.loading ? "No draft or ready campaigns. Create one first." : undefined}>
          <Select id="bulk-campaign" value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
            <option value="">{campaigns.loading ? "Loading…" : "Choose a campaign"}</option>
            {open.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
        {protectedCount > 0 && (
          <Checkbox
            checked={includeProtected}
            onChange={(e) => setIncludeProtected(e.target.checked)}
            label={
              <span>
                Include {protectedCount} protected {protectedCount === 1 ? "company" : "companies"}{" "}
                <span className="text-fg-muted">(protected, already in Odoo)</span>
              </span>
            }
          />
        )}
      </div>
    </ConfirmDialog>
  );
}

function PersonCell({ name }: { name?: string | null }) {
  if (!name) return <span className="text-fg-subtle">—</span>;
  return (
    <span className="inline-flex items-center gap-2 text-fg-muted">
      <Avatar name={name} size="sm" />
      {name}
    </span>
  );
}

/** Saved filter combinations, kept in this browser only (a personal convenience, not shared data). */
type SavedView = { name: string; filters: Record<string, string> };
const VIEWS_KEY = "lf.companies.views";
const VIEW_KEYS = ["q", "crm_status", "protected", "source", "country", "sort"] as const;

function readViews(): SavedView[] {
  try {
    return JSON.parse(localStorage.getItem(VIEWS_KEY) ?? "[]") as SavedView[];
  } catch {
    return [];
  }
}
function writeViews(views: SavedView[]) {
  try {
    localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
  } catch {
    /* storage unavailable: views just are not remembered */
  }
}

function SavedViews({
  current,
  name,
  canSave,
  onApply,
}: {
  current: Record<string, string>;
  name: string;
  canSave: boolean;
  onApply: (filters: Record<string, string>) => void;
}) {
  const [views, setViews] = useState<SavedView[]>([]);
  useEffect(() => setViews(readViews()), []);
  const same = (v: SavedView) => VIEW_KEYS.every((k) => (v.filters[k] ?? "") === (current[k] ?? ""));
  const activeView = views.find(same);
  if (!views.length && !canSave) return null;

  function save() {
    const next = [...views.filter((v) => v.name !== name), { name, filters: Object.fromEntries(VIEW_KEYS.map((k) => [k, current[k] ?? ""])) }].slice(-8);
    setViews(next);
    writeViews(next);
    toast.success("View saved", `“${name}” is one click away above the list.`);
  }
  function remove(view: SavedView) {
    const next = views.filter((v) => v !== view);
    setViews(next);
    writeViews(next);
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-4 py-2.5">
      <span className="mr-1 inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-fg-subtle">
        <Bookmark className="h-3 w-3" aria-hidden /> Views
      </span>
      {views.map((v) => {
        const active = v === activeView;
        return (
          <span
            key={v.name}
            className={
              active
                ? "inline-flex h-7 animate-pop-in items-center overflow-hidden rounded-full border border-accent bg-accent text-xs font-medium text-white"
                : "inline-flex h-7 animate-pop-in items-center overflow-hidden rounded-full border border-border bg-surface text-xs font-medium text-fg-muted transition-colors hover:border-accent/40 hover:text-fg"
            }
          >
            <button type="button" className="h-full pl-3 pr-2" onClick={() => onApply(v.filters)} aria-pressed={active}>
              {v.name}
            </button>
            <button
              type="button"
              onClick={() => remove(v)}
              className="flex h-full items-center pr-2 opacity-60 transition-opacity hover:opacity-100"
              aria-label={`Delete view ${v.name}`}
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          </span>
        );
      })}
      {canSave && !activeView && (
        <button
          type="button"
          onClick={save}
          className="inline-flex h-7 items-center gap-1 rounded-full border border-dashed border-border-strong px-3 text-xs font-medium text-fg-muted transition-colors hover:border-accent hover:text-accent"
        >
          <BookmarkPlus className="h-3.5 w-3.5" aria-hidden /> Save view
        </button>
      )}
    </div>
  );
}

function CompaniesView() {
  const privileged = isPrivileged(useCurrentUser());
  const [filters, setFilters] = useUrlState(KEYS);
  const commitSearch = useCallback((q: string) => setFilters({ q }), [setFilters]);
  const [search, setSearch] = useDebouncedSearch(filters.q, commitSearch);
  const page = Number(filters.page) || 1;
  const [selected, setSelected] = useState<Map<number, Company>>(new Map());
  const [adding, setAdding] = useState<Company[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<Page<Company>>("/companies", {
    q: filters.q,
    crm_status: filters.crm_status,
    protected: filters.protected,
    source: filters.source,
    country: filters.country,
    sort: filters.sort || "created",
    page,
    page_size: PAGE_SIZE,
  });
  const tokens = filterTokens(filters);
  const filtered = Boolean(filters.q || tokens.length);

  const selection = {
    selected: new Set(selected.keys()),
    onChange: (ids: Set<number>) => {
      const next = new Map<number, Company>();
      ids.forEach((id) => {
        const company = selected.get(id) ?? data?.items.find((c) => c.id === id);
        if (company) next.set(id, company);
      });
      setSelected(next);
    },
  };

  async function researchSelected() {
    try {
      const result = await api<ResearchStartResult>("/research", { method: "POST", body: { company_ids: [...selected.keys()] } });
      const skipped = result.skipped.map((s) => `${s.name}: ${s.reason}`).join(" ");
      setNotice(`Research started for ${result.runs.length} compan${result.runs.length === 1 ? "y" : "ies"}. Results appear under Qualified leads.${skipped ? ` Skipped — ${skipped}` : ""}`);
      setSelected(new Map());
    } catch (err) {
      toast.error("Could not start the research", err instanceof ApiError ? err.message : undefined);
    }
  }

  async function findDecisionMakers() {
    try {
      const result = await api<{ runs: unknown[]; skipped: { name: string; reason: string }[] }>("/decision-makers/search", {
        method: "POST",
        body: { company_ids: [...selected.keys()] },
      });
      const skipped = result.skipped.map((s) => `${s.name}: ${s.reason}`).join(" ");
      setNotice(`Decision-maker search started for ${result.runs.length} compan${result.runs.length === 1 ? "y" : "ies"} (website and Apollo search only — no credits).${skipped ? ` Skipped — ${skipped}` : ""}`);
      setSelected(new Map());
    } catch (err) {
      toast.error("Could not start the decision-maker search", err instanceof ApiError ? err.message : undefined);
    }
  }

  return (
    <>
      {notice && (
        <div className="mb-4">
          <Alert tone="success">{notice}</Alert>
        </div>
      )}
      <Section flush>
        <SavedViews
          current={filters}
          canSave={filtered}
          name={[filters.q && `“${filters.q}”`, ...tokens.map((t) => t.value)].filter(Boolean).join(" · ") || "All companies"}
          onApply={(f) => {
            setSearch(f.q ?? "");
            setFilters({ ...f, page: "" });
          }}
        />
        <Toolbar
          end={
            <Select
              aria-label="Sort by"
              className="w-[150px]"
              value={filters.sort || "created"}
              onChange={(e) => setFilters({ sort: e.target.value === "created" ? "" : e.target.value })}
            >
              <option value="created">Newest first</option>
              <option value="updated">Recently updated</option>
              <option value="name">Name A–Z</option>
              <option value="status">Relationship</option>
            </Select>
          }
        >
          <SearchInput className="w-full sm:w-64" value={search} onChange={setSearch} placeholder="Search name, domain or city" label="Search companies" />
          <Select aria-label="Protected or not" className="w-[160px]" value={filters.protected} onChange={(e) => setFilters({ protected: e.target.value, crm_status: "" })}>
            <option value="">Protected or not</option>
            <option value="true">Protected (in Odoo)</option>
            <option value="false">Not protected</option>
          </Select>
          <Select aria-label="Odoo status" className="w-[160px]" value={filters.crm_status} onChange={(e) => setFilters({ crm_status: e.target.value, protected: "" })}>
            <option value="">Odoo status</option>
            {ODOO_STATUSES.map((s) => (
              <option key={s} value={s}>
                {ODOO_STATUS_LABEL[s]}
              </option>
            ))}
          </Select>
          <Select aria-label="Source" className="w-[132px]" value={filters.source} onChange={(e) => setFilters({ source: e.target.value })}>
            <option value="">Source</option>
            {(Object.keys(SOURCE_LABEL) as CompanySource[]).map((s) => (
              <option key={s} value={s}>
                {SOURCE_LABEL[s]}
              </option>
            ))}
          </Select>
          <Select aria-label="Country" className="w-[140px]" value={filters.country} onChange={(e) => setFilters({ country: e.target.value })}>
            <option value="">Country</option>
            {countryNames().map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        </Toolbar>

        {tokens.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 border-b border-border bg-surface-muted/40 px-4 py-2" aria-label="Active filters">
            {tokens.map((t) => (
              <span key={t.key} className="inline-flex h-6 animate-pop-in items-center overflow-hidden rounded-sm border border-border bg-surface text-xs shadow-xs">
                <span className="px-2 text-fg-muted">{t.field}</span>
                <span className="border-l border-border px-2 font-medium text-fg">{t.value}</span>
                <button
                  type="button"
                  onClick={() => setFilters({ [t.key]: "" })}
                  className="flex h-full items-center border-l border-border px-1.5 text-fg-subtle hover:bg-surface-hover hover:text-fg"
                  aria-label={`Remove ${t.field} filter`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            <button
              type="button"
              className="ml-1 text-xs text-fg-muted hover:text-fg"
              onClick={() => {
                setSearch("");
                setFilters({ q: "", crm_status: "", protected: "", source: "", country: "" });
              }}
            >
              Clear all
            </button>
            {data && <span className="ml-auto text-xs tabular text-fg-muted">{data.total.toLocaleString()} results</span>}
          </div>
        )}

        <DataTable<Company, number>
          caption="Companies"
          rows={data?.items}
          loading={loading}
          error={error?.message}
          onRetry={reload}
          rowKey={(c) => c.id}
          rowHref={(c) => `/companies/${c.id}`}
          selection={selection}
          sort={filters.sort || "created"}
          onSort={(key) => setFilters({ sort: key === "created" ? "" : key })}
          empty={
            <EmptyState
              icon={<Building2 />}
              title={filtered ? "No companies match these filters" : "No companies yet"}
              description={
                filtered ? "Try a different search, or remove a filter." : "Import TECOMSA's Odoo contacts, or add a company manually."
              }
              action={
                !filtered && (
                  <>
                    <ButtonLink href="/data-sources/odoo" variant="secondary" size="sm">
                      <Upload className="h-3.5 w-3.5" aria-hidden /> Import Odoo contacts
                    </ButtonLink>
                    <ButtonLink href="/companies/new" size="sm">
                      <Plus className="h-3.5 w-3.5" aria-hidden /> Add company
                    </ButtonLink>
                  </>
                )
              }
            />
          }
          columns={[
            {
              key: "name",
              header: "Company",
              sortKey: "name",
              cell: (c) => (
                <div className="flex min-w-[220px] max-w-[320px] items-center gap-2.5">
                  <Avatar name={c.name} size="sm" domain={c.domain} />
                  <div className="min-w-0 leading-tight">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate">
                        <RowLink href={`/companies/${c.id}`}>{c.name}</RowLink>
                      </span>
                      {c.source === "DEMO" && <Badge tone="warning">Demo</Badge>}
                    </span>
                    {c.domain && <p className="truncate text-[11.5px] text-fg-subtle">{c.domain}</p>}
                  </div>
                </div>
              ),
            },
            { key: "crm", header: "Relationship", sortKey: "status", cell: (c) => <CrmStatusBadge status={c.odoo_status} /> },
            {
              key: "phone",
              header: "Phone",
              cell: (c) =>
                c.main_phone ? (
                  <a href={`tel:${c.main_phone.replace(/[^\d+]/g, "")}`} className="tabular text-fg-muted hover:text-accent hover:underline">
                    {c.main_phone}
                  </a>
                ) : (
                  <span className="text-fg-subtle">—</span>
                ),
            },
            {
              key: "email",
              header: "Email",
              cell: (c) =>
                c.main_email ? (
                  <a href={`mailto:${c.main_email}`} className="block max-w-[200px] truncate text-fg-muted hover:text-accent hover:underline" title={c.main_email}>
                    {c.main_email}
                  </a>
                ) : (
                  <span className="text-fg-subtle">—</span>
                ),
            },
            { key: "loc", header: "Location", cell: (c) => <span className="text-fg-muted">{location(c.city, c.country)}</span> },
            { key: "owner", header: "Owner", cell: (c) => <PersonCell name={c.salesperson?.name} /> },
            ...(privileged
              ? [{ key: "found", header: "Found by", cell: (c: Company) => <PersonCell name={c.owner?.name} /> }]
              : []),
            { key: "created", header: "Added", sortKey: "created", cell: (c) => <span className="tabular text-fg-subtle">{formatDate(c.created_at)}</span> },
          ]}
        />
        {data && (
          <div className="border-t border-border">
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={(p) => setFilters({ page: String(p) })} />
          </div>
        )}
      </Section>

      <SelectionBar count={selected.size} onClear={() => setSelected(new Map())}>
        <Button variant="ghost" size="sm" onClick={() => setAdding([...selected.values()])}>
          <Megaphone className="h-3.5 w-3.5" aria-hidden /> Add to campaign
        </Button>
        <Button variant="ghost" size="sm" onClick={() => void researchSelected()}>
          <Search className="h-3.5 w-3.5" aria-hidden /> Research selected
        </Button>
        <Button variant="ghost" size="sm" onClick={() => void findDecisionMakers()}>
          <UserSearch className="h-3.5 w-3.5" aria-hidden /> Find decision makers
        </Button>
        <Button variant="ghost" size="sm" onClick={() => exportCompanies([...selected.values()])}>
          <Download className="h-3.5 w-3.5" aria-hidden /> Export CSV
        </Button>
      </SelectionBar>

      <AddToCampaignDialog
        companies={adding}
        onClose={() => setAdding([])}
        onDone={(msg) => {
          setAdding([]);
          setSelected(new Map());
          setNotice(msg);
          void reload();
        }}
      />
    </>
  );
}

export default function CompaniesPage() {
  return (
    <>
      <PageHeader
        title="Companies"
        description="Every company LeadFinder knows. Protected companies already have a relationship in TECOMSA's Odoo."
        actions={
          <ButtonLink href="/companies/new">
            <Plus className="h-3.5 w-3.5" aria-hidden /> Add company
          </ButtonLink>
        }
      />
      <Suspense>
        <CompaniesView />
      </Suspense>
    </>
  );
}
