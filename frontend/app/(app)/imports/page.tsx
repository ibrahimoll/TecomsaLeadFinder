"use client";

import { History } from "lucide-react";
import { Suspense } from "react";

import { RequireCapability } from "@/components/guard";
import { ImportsTable } from "@/components/import-table";
import {
  ButtonLink,
  EmptyState,
  PageHeader,
  Pagination,
  Section,
  Select,
  Toolbar,
} from "@/components/ui";
import { useApi } from "@/lib/api";
import { IMPORT_TYPE_LABEL } from "@/lib/constants";
import { useUrlState } from "@/lib/use-url-state";
import type { ImportRun, Page } from "@/types";

const PAGE_SIZE = 50;

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
          <option value="PREVIEW">Preview · not imported</option>
          <option value="FAILED">Failed</option>
          <option value="CANCELLED">Cancelled</option>
        </Select>
      </Toolbar>
      <ImportsTable
        rows={data?.items}
        loading={loading}
        error={error?.message}
        onRetry={reload}
        onChanged={reload}
        empty={
          <EmptyState
            icon={<History className="h-5 w-5" />}
            title={filters.import_type || filters.status ? "No imports match these filters" : "No Odoo files have been imported yet."}
            action={<ButtonLink href="/data-sources/odoo" size="sm">Import Odoo contacts</ButtonLink>}
          />
        }
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
        breadcrumbs={[{ label: "Data sources" }, { label: "Odoo", href: "/data-sources/odoo" }, { label: "Import history" }]}
        title="Import history"
        description="Every uploaded Odoo file and what happened to it. Delete an import with or without its data."
        actions={<ButtonLink href="/data-sources/odoo">New import</ButtonLink>}
      />
      <Suspense>
        <ImportHistoryTable />
      </Suspense>
    </RequireCapability>
  );
}
