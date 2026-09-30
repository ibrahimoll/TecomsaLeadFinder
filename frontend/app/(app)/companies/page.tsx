"use client";

import { Building2, Plus } from "lucide-react";
import { Suspense, useCallback } from "react";

import { CrmStatusBadge, SourceBadge } from "@/components/status-badges";
import {
  Avatar,
  Button,
  ButtonLink,
  DataTable,
  EmptyState,
  PageHeader,
  Pagination,
  RowLink,
  SearchInput,
  Section,
  Select,
  Toolbar,
} from "@/components/ui";
import { useApi } from "@/lib/api";
import { countryNames, ODOO_STATUS_LABEL, ODOO_STATUSES, SOURCE_LABEL } from "@/lib/constants";
import { dash, formatDate, location } from "@/lib/format";
import { useDebouncedSearch, useUrlState } from "@/lib/use-url-state";
import type { Company, CompanySource, Page } from "@/types";

const PAGE_SIZE = 50;
const KEYS = ["q", "crm_status", "protected", "source", "country", "sort", "page"] as const;

function CompaniesView() {
  const [filters, setFilters] = useUrlState(KEYS);
  const commitSearch = useCallback((q: string) => setFilters({ q }), [setFilters]);
  const [search, setSearch] = useDebouncedSearch(filters.q, commitSearch);
  const page = Number(filters.page) || 1;

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
  const filtered = Boolean(filters.q || filters.crm_status || filters.protected || filters.source || filters.country);

  return (
    <Section flush>
      <Toolbar
        end={
          <Select
            aria-label="Sort by"
            className="w-40"
            value={filters.sort || "created"}
            onChange={(e) => setFilters({ sort: e.target.value === "created" ? "" : e.target.value })}
          >
            <option value="created">Newest first</option>
            <option value="updated">Recently updated</option>
            <option value="name">Name A–Z</option>
            <option value="status">CRM status</option>
          </Select>
        }
      >
        <SearchInput className="w-full sm:w-72" value={search} onChange={setSearch} placeholder="Search name, domain or city" label="Search companies" />
        <Select
          aria-label="Relationship"
          className="w-40"
          value={filters.protected}
          onChange={(e) => setFilters({ protected: e.target.value, crm_status: "" })}
        >
          <option value="">All relationships</option>
          <option value="true">Protected (in Odoo)</option>
          <option value="false">Not protected</option>
        </Select>
        <Select
          aria-label="CRM status"
          className="w-44"
          value={filters.crm_status}
          onChange={(e) => setFilters({ crm_status: e.target.value, protected: "" })}
        >
          <option value="">Any CRM status</option>
          {ODOO_STATUSES.map((s) => (
            <option key={s} value={s}>
              {ODOO_STATUS_LABEL[s]}
            </option>
          ))}
        </Select>
        <Select aria-label="Source" className="w-36" value={filters.source} onChange={(e) => setFilters({ source: e.target.value })}>
          <option value="">Any source</option>
          {(Object.keys(SOURCE_LABEL) as CompanySource[]).map((s) => (
            <option key={s} value={s}>
              {SOURCE_LABEL[s]}
            </option>
          ))}
        </Select>
        <Select aria-label="Country" className="w-40" value={filters.country} onChange={(e) => setFilters({ country: e.target.value })}>
          <option value="">Any country</option>
          {countryNames().map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
        {filtered && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSearch("");
              setFilters({ q: "", crm_status: "", protected: "", source: "", country: "" });
            }}
          >
            Clear filters
          </Button>
        )}
      </Toolbar>
      <DataTable
        caption="Companies"
        rows={data?.items}
        loading={loading}
        error={error?.message}
        onRetry={reload}
        rowKey={(c) => c.id}
        sort={filters.sort || "created"}
        onSort={(key) => setFilters({ sort: key === "created" ? "" : key })}
        empty={
          <EmptyState
            icon={<Building2 className="h-5 w-5" />}
            title={filtered ? "No companies match these filters" : "No companies yet"}
            description={
              filtered
                ? "Try a different search or clear the filters."
                : "Import TECOMSA's Odoo contacts and CRM records, or add a company manually."
            }
            action={!filtered && <ButtonLink href="/companies/new" size="sm">Add company</ButtonLink>}
          />
        }
        columns={[
          {
            key: "name",
            header: "Company",
            sortKey: "name",
            cell: (c) => (
              <div className="flex min-w-[220px] items-center gap-2.5">
                <Avatar name={c.name} size="sm" />
                <div className="min-w-0 leading-tight">
                  <RowLink href={`/companies/${c.id}`}>{c.name}</RowLink>
                  <p className="truncate text-xs text-fg-muted">{c.domain ?? "No website"}</p>
                </div>
              </div>
            ),
          },
          { key: "industry", header: "Industry", cell: (c) => <span className="text-fg-muted">{dash(c.industry)}</span> },
          { key: "loc", header: "Location", cell: (c) => <span className="text-fg-muted">{location(c.city, c.country)}</span> },
          { key: "source", header: "Source", cell: (c) => <SourceBadge source={c.source} /> },
          { key: "crm", header: "CRM status", sortKey: "status", cell: (c) => <CrmStatusBadge status={c.odoo_status} /> },
          { key: "owner", header: "Salesperson", cell: (c) => <span className="text-fg-muted">{c.salesperson?.name ?? "—"}</span> },
          { key: "created", header: "Added", sortKey: "created", cell: (c) => <span className="text-fg-muted">{formatDate(c.created_at)}</span> },
        ]}
      />
      {data && (
        <div className="border-t border-border">
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={(p) => setFilters({ page: String(p) })} />
        </div>
      )}
    </Section>
  );
}

export default function CompaniesPage() {
  return (
    <>
      <PageHeader
        title="Companies"
        description="TECOMSA's company database. Protected companies already have a relationship in Odoo."
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
