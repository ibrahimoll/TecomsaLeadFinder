"use client";

import { Megaphone, Plus } from "lucide-react";
import { Suspense, useCallback } from "react";

import { CampaignStatusBadge, DivisionBadge } from "@/components/status-badges";
import {
  Avatar,
  Button,
  ButtonLink,
  Checkbox,
  DataTable,
  EmptyState,
  FilterPills,
  Meter,
  PageHeader,
  Pagination,
  RowLink,
  SearchInput,
  Section,
  Select,
  Toolbar,
} from "@/components/ui";
import { useApi } from "@/lib/api";
import { CAMPAIGN_STATUS_LABEL, DIVISIONS } from "@/lib/constants";
import { dash, formatDate } from "@/lib/format";
import { useDebouncedSearch, useUrlState } from "@/lib/use-url-state";
import type { Campaign, CampaignStatus, Page } from "@/types";

const PAGE_SIZE = 50;
const KEYS = ["q", "status", "division", "mine", "page"] as const;
const STATUS_DOT: Record<CampaignStatus, string> = {
  DRAFT: "bg-fg-subtle",
  READY: "bg-info",
  RUNNING: "bg-accent",
  COMPLETED: "bg-success",
  FAILED: "bg-danger",
  CANCELLED: "bg-border-strong",
};

function CampaignsView() {
  const [filters, setFilters] = useUrlState(KEYS);
  const commitSearch = useCallback((q: string) => setFilters({ q }), [setFilters]);
  const [search, setSearch] = useDebouncedSearch(filters.q, commitSearch);
  const page = Number(filters.page) || 1;

  const { data, error, loading, reload } = useApi<Page<Campaign>>("/campaigns", {
    q: filters.q,
    status: filters.status,
    division: filters.division,
    mine: filters.mine === "1" || undefined,
    page,
    page_size: PAGE_SIZE,
  });
  const filtered = Boolean(filters.q || filters.status || filters.division || filters.mine);

  return (
    <Section flush>
      <div className="border-b border-border px-4 py-3">
        <FilterPills<string>
          label="Campaign status"
          value={filters.status}
          onChange={(status) => setFilters({ status })}
          options={[
            { value: "", label: "All campaigns" },
            ...(Object.keys(CAMPAIGN_STATUS_LABEL) as CampaignStatus[]).map((s) => ({ value: s, label: CAMPAIGN_STATUS_LABEL[s], dot: STATUS_DOT[s] })),
          ]}
        />
      </div>
      <Toolbar>
        <SearchInput className="w-full sm:w-64" value={search} onChange={setSearch} placeholder="Search campaigns" label="Search campaigns" />
        <Select aria-label="Division" className="w-36" value={filters.division} onChange={(e) => setFilters({ division: e.target.value })}>
          <option value="">All divisions</option>
          {DIVISIONS.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </Select>
        <Checkbox label="Created by me" checked={filters.mine === "1"} onChange={(e) => setFilters({ mine: e.target.checked ? "1" : "" })} />
        {filtered && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSearch("");
              setFilters({ q: "", status: "", division: "", mine: "" });
            }}
          >
            Clear filters
          </Button>
        )}
      </Toolbar>
      <DataTable
        caption="Campaigns"
        rows={data?.items}
        loading={loading}
        error={error?.message}
        onRetry={reload}
        rowKey={(c) => c.id}
        rowHref={(c) => `/campaigns/${c.id}`}
        empty={
          <EmptyState
            icon={<Megaphone className="h-5 w-5" />}
            title={filtered ? "No campaigns match these filters" : "No campaigns yet"}
            description={filtered ? undefined : "A campaign defines which companies and roles a TECOMSA division should target."}
            action={!filtered && <ButtonLink href="/campaigns/new" size="sm">New campaign</ButtonLink>}
          />
        }
        columns={[
          {
            key: "name",
            header: "Campaign",
            cell: (c) => (
              <div className="min-w-[220px] max-w-[340px] py-1">
                <div className="min-w-0 leading-tight">
                  <span className="block truncate">
                    <RowLink href={`/campaigns/${c.id}`}>{c.name}</RowLink>
                  </span>
                  <span className="block truncate text-[11.5px] text-fg-subtle">
                    {[c.city, c.region, c.country].filter(Boolean).join(", ") || "Any market"} · {dash(c.industry)}
                  </span>
                </div>
              </div>
            ),
          },
          { key: "division", header: "Division", cell: (c) => <DivisionBadge division={c.tecomsa_division} /> },
          { key: "companies", header: "Companies", align: "right", cell: (c) => <Meter value={c.company_count} max={c.target_company_count} /> },
          { key: "status", header: "Status", cell: (c) => <CampaignStatusBadge status={c.status} /> },
          {
            key: "creator",
            header: "Created by",
            cell: (c) => (
              <span className="inline-flex items-center gap-2 text-fg-muted">
                <Avatar name={c.creator.name} size="sm" /> {c.creator.name}
              </span>
            ),
          },
          { key: "created", header: "Created", cell: (c) => <span className="text-fg-muted">{formatDate(c.created_at)}</span> },
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

export default function CampaignsPage() {
  return (
    <>
      <PageHeader
        title="Campaigns"
        description="Targeting definitions per TECOMSA division. No external searches run in this version."
        actions={
          <ButtonLink href="/campaigns/new">
            <Plus className="h-3.5 w-3.5" aria-hidden /> New campaign
          </ButtonLink>
        }
      />
      <Suspense>
        <CampaignsView />
      </Suspense>
    </>
  );
}
