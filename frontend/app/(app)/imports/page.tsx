"use client";

import { History } from "lucide-react";
import { Suspense } from "react";

import { RequireCapability } from "@/components/guard";
import { ImportStatusBadge } from "@/components/status-badges";
import {
  ButtonLink,
  DataTable,
  EmptyState,
  PageHeader,
  Pagination,
  RowLink,
  Section,
  Select,
  Toolbar,
} from "@/components/ui";
import { useApi } from "@/lib/api";
import { IMPORT_TYPE_LABEL } from "@/lib/constants";
import { formatDateTime } from "@/lib/format";
import { useUrlState } from "@/lib/use-url-state";
import type { ImportRun, Page } from "@/types";

const PAGE_SIZE = 50;

function num(n: number) {
  return n === 0 ? <span className="text-fg-subtle">0</span> : n.toLocaleString();
}

function ImportHistoryTable() {
  const [filters, setFilters] = useUrlState(["import_type", "status", "page"] as const);
  const page = Number(filters.page) || 1;
  const { data, error, loading, reload } = useApi<Page<ImportRun>>("/imports", {
    import_type: filters.import_type,
    status: filters.status,
    page,
    page_size: PAGE_SIZE,
  });

  return (
    <Section flush>
      <Toolbar>
        <Select aria-label="Import type" className="w-56" value={filters.import_type} onChange={(e) => setFilters({ import_type: e.target.value })}>
          <option value="">All import types</option>
          <option value="ODOO_CRM">{IMPORT_TYPE_LABEL.ODOO_CRM}</option>
          <option value="ODOO_CONTACTS">{IMPORT_TYPE_LABEL.ODOO_CONTACTS}</option>
        </Select>
        <Select aria-label="Status" className="w-48" value={filters.status} onChange={(e) => setFilters({ status: e.target.value })}>
          <option value="">All statuses</option>
          <option value="COMPLETED">Completed</option>
          <option value="PREVIEW">Awaiting confirmation</option>
          <option value="FAILED">Failed</option>
          <option value="CANCELLED">Cancelled</option>
        </Select>
      </Toolbar>
      <DataTable
        caption="Import history"
        rows={data?.items}
        loading={loading}
        error={error?.message}
        onRetry={reload}
        rowKey={(r) => r.id}
        empty={
          <EmptyState
            icon={<History className="h-5 w-5" />}
            title="No imports recorded"
            action={<ButtonLink href="/data-sources/odoo" size="sm">Import from Odoo</ButtonLink>}
          />
        }
        columns={[
          {
            key: "file",
            header: "Import",
            cell: (r) => (
              <div className="leading-tight">
                <RowLink href={`/imports/${r.id}`}>{r.original_filename}</RowLink>
                <p className="text-xs text-fg-muted">{IMPORT_TYPE_LABEL[r.import_type]}</p>
              </div>
            ),
          },
          { key: "at", header: "Date", cell: (r) => <span className="text-fg-muted">{formatDateTime(r.completed_at ?? r.created_at)}</span> },
          { key: "rows", header: "Rows", align: "right", cell: (r) => num(r.row_count) },
          { key: "ins", header: "Imported", align: "right", cell: (r) => num(r.inserted_count) },
          { key: "upd", header: "Updated", align: "right", cell: (r) => num(r.updated_count) },
          { key: "skip", header: "Skipped", align: "right", cell: (r) => num(r.skipped_count) },
          { key: "err", header: "Errors", align: "right", cell: (r) => num(r.error_count) },
          { key: "status", header: "Status", cell: (r) => <ImportStatusBadge status={r.status} /> },
          { key: "by", header: "By", cell: (r) => <span className="text-fg-muted">{r.creator?.name ?? "—"}</span> },
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

export default function ImportHistoryPage() {
  return (
    <RequireCapability capability="run_imports">
      <PageHeader
        breadcrumbs={[{ label: "Data sources" }, { label: "Import history" }]}
        title="Import history"
        description="Every uploaded Odoo file and what happened to it."
        actions={<ButtonLink href="/data-sources/odoo">New import</ButtonLink>}
      />
      <Suspense>
        <ImportHistoryTable />
      </Suspense>
    </RequireCapability>
  );
}
