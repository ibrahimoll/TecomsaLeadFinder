"use client";

import { Database, Plus } from "lucide-react";
import Link from "next/link";

import { ActivityList } from "@/components/activity-list";
import { CampaignStatusBadge, CrmStatusBadge, ImportStatusBadge } from "@/components/status-badges";
import {
  Alert,
  ButtonLink,
  DataTable,
  EmptyState,
  ErrorState,
  MetricStrip,
  PageHeader,
  RowLink,
  Section,
  type Metric,
} from "@/components/ui";
import { useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { DIVISION_LABEL, IMPORT_TYPE_LABEL } from "@/lib/constants";
import { formatDate, formatDateTime, location } from "@/lib/format";
import type { DashboardSummary } from "@/types";

export default function DashboardPage() {
  const user = useCurrentUser();
  const { data, error, loading, reload } = useApi<DashboardSummary>("/dashboard");

  const metrics: Metric[] = [
    { label: "Companies", value: data?.total_companies ?? 0, href: "/companies" },
    { label: "Protected", value: data?.protected_companies ?? 0, href: "/companies?protected=true", hint: "Known in Odoo" },
    { label: "Available", value: data?.available_companies ?? 0, href: "/companies?protected=false", hint: "No Odoo match" },
  ];
  if (user.capabilities.view_crm) {
    metrics.push(
      { label: "Odoo CRM records", value: data?.odoo_crm_records ?? 0, href: "/crm", hint: `${data?.odoo_open_records ?? 0} open` },
      { label: "Odoo contacts", value: data?.odoo_contacts ?? 0, href: "/crm?tab=contacts" },
    );
  }
  metrics.push({ label: "My campaigns", value: data?.my_campaigns ?? 0, href: "/campaigns?mine=1" });

  const noOdooData = data && data.odoo_crm_records === 0 && data.odoo_contacts === 0;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={`Signed in as ${user.name}`}
        actions={
          <>
            <ButtonLink href="/companies/new" variant="secondary">
              <Plus className="h-3.5 w-3.5" aria-hidden /> Add company
            </ButtonLink>
            <ButtonLink href="/campaigns/new">
              <Plus className="h-3.5 w-3.5" aria-hidden /> New campaign
            </ButtonLink>
          </>
        }
      />

      {error ? (
        <Section>
          <ErrorState message={error.message} onRetry={reload} />
        </Section>
      ) : (
        <div className="space-y-5">
          <MetricStrip items={metrics} loading={loading && !data} />

          {noOdooData && (
            <Alert tone="info" title="No Odoo data imported yet">
              Until TECOMSA&apos;s Odoo CRM and contacts are imported, LeadFinder cannot tell which companies are already
              known, so every company shows as <strong>Not checked</strong>.
              {user.capabilities.run_imports && (
                <>
                  {" "}
                  <Link href="/data-sources/odoo" className="font-medium underline">
                    Import from Odoo
                  </Link>
                </>
              )}
            </Alert>
          )}

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <div className="space-y-5 xl:col-span-2">
              <Section
                title="Recently added companies"
                flush
                actions={<ButtonLink href="/companies" variant="ghost" size="sm">View all</ButtonLink>}
              >
                <DataTable
                  caption="Recently added companies"
                  rows={data?.recent_companies}
                  loading={loading}
                  rowKey={(c) => c.id}
                  empty={
                    <EmptyState
                      compact
                      title="No companies yet"
                      description="Companies appear here when they are added manually or imported from Odoo."
                    />
                  }
                  columns={[
                    { key: "name", header: "Company", cell: (c) => <RowLink href={`/companies/${c.id}`}>{c.name}</RowLink> },
                    { key: "loc", header: "Location", cell: (c) => <span className="text-fg-muted">{location(c.city, c.country)}</span> },
                    { key: "crm", header: "CRM status", cell: (c) => <CrmStatusBadge status={c.odoo_status} /> },
                    { key: "added", header: "Added", cell: (c) => <span className="text-fg-muted">{formatDate(c.created_at)}</span> },
                  ]}
                />
              </Section>

              <Section
                title="Recent campaigns"
                flush
                actions={<ButtonLink href="/campaigns" variant="ghost" size="sm">View all</ButtonLink>}
              >
                <DataTable
                  caption="Recent campaigns"
                  rows={data?.recent_campaigns}
                  loading={loading}
                  rowKey={(c) => c.id}
                  empty={<EmptyState compact title="No campaigns yet" />}
                  columns={[
                    { key: "name", header: "Campaign", cell: (c) => <RowLink href={`/campaigns/${c.id}`}>{c.name}</RowLink> },
                    { key: "div", header: "Division", cell: (c) => DIVISION_LABEL[c.tecomsa_division] },
                    { key: "target", header: "Target", align: "right", cell: (c) => c.target_company_count },
                    { key: "status", header: "Status", cell: (c) => <CampaignStatusBadge status={c.status} /> },
                  ]}
                />
              </Section>

              {isPrivileged(user) && user.capabilities.run_imports && (
                <Section
                  title="Latest Odoo imports"
                  flush
                  actions={<ButtonLink href="/imports" variant="ghost" size="sm">History</ButtonLink>}
                >
                  <DataTable
                    caption="Latest Odoo imports"
                    rows={data?.latest_imports}
                    loading={loading}
                    rowKey={(r) => r.id}
                    empty={
                      <EmptyState
                        compact
                        icon={<Database className="h-5 w-5" />}
                        title="No imports yet"
                        action={<ButtonLink href="/data-sources/odoo" size="sm">Import from Odoo</ButtonLink>}
                      />
                    }
                    columns={[
                      { key: "file", header: "File", cell: (r) => <RowLink href={`/imports/${r.id}`}>{r.original_filename}</RowLink> },
                      { key: "type", header: "Type", cell: (r) => IMPORT_TYPE_LABEL[r.import_type] },
                      { key: "rows", header: "Rows", align: "right", cell: (r) => r.row_count.toLocaleString() },
                      { key: "status", header: "Status", cell: (r) => <ImportStatusBadge status={r.status} /> },
                      { key: "at", header: "Uploaded", cell: (r) => <span className="text-fg-muted">{formatDateTime(r.created_at)}</span> },
                    ]}
                  />
                </Section>
              )}
            </div>

            <Section title={isPrivileged(user) ? "Team activity" : "My activity"}>
              <ActivityList items={data?.recent_activity} loading={loading} />
            </Section>
          </div>
        </div>
      )}
    </>
  );
}
