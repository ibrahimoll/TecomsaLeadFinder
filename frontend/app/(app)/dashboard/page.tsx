"use client";

import Link from "next/link";

import { ActivityList } from "@/components/activity-list";
import { OdooStatusBadge } from "@/components/status-badges";
import { Alert, ButtonLink, Card, EmptyState, Loading, PageHeader, Table, Td, Th } from "@/components/ui";
import { useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { dash, formatDate } from "@/lib/format";
import type { DashboardSummary } from "@/types";

function Stat({ label, value, href, note }: { label: string; value: number; href?: string; note?: string }) {
  const body = (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 hover:border-slate-300">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{value}</p>
      {note && <p className="mt-0.5 text-xs text-slate-500">{note}</p>}
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

export default function DashboardPage() {
  const user = useCurrentUser();
  const { data, error, loading } = useApi<DashboardSummary>("/dashboard");

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={`Welcome back, ${user.name}.`}
        actions={
          <>
            <ButtonLink href="/companies/new" variant="secondary">
              Add company
            </ButtonLink>
            <ButtonLink href="/campaigns/new">New campaign</ButtonLink>
          </>
        }
      />
      {error && <Alert>{error.message}</Alert>}
      {loading && !data && <Loading />}
      {data && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Total companies" value={data.total_companies} href="/companies" />
            <Stat label="My campaigns" value={data.my_campaigns} href="/campaigns?mine=1" />
            <Stat label="Draft campaigns" value={data.draft_campaigns} href="/campaigns?status=DRAFT" />
            <Stat label="Lusha credits used" value={data.lusha_credits_used} note="Lusha is not connected" />
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
            <Card title="Recent companies" className="lg:col-span-3" bodyClassName="p-0">
              {data.recent_companies.length === 0 ? (
                <EmptyState
                  title="No companies yet"
                  description="Companies you add manually will appear here."
                  action={<ButtonLink href="/companies/new">Add company</ButtonLink>}
                />
              ) : (
                <Table>
                  <thead>
                    <tr>
                      <Th>Company</Th>
                      <Th>Country</Th>
                      <Th>Odoo status</Th>
                      <Th>Added</Th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.recent_companies.map((c) => (
                      <tr key={c.id} className="hover:bg-slate-50">
                        <Td>
                          <Link href={`/companies/${c.id}`} className="font-medium text-brand-700 hover:underline">
                            {c.name}
                          </Link>
                        </Td>
                        <Td>{dash(c.country)}</Td>
                        <Td>
                          <OdooStatusBadge status={c.odoo_status} />
                        </Td>
                        <Td>{formatDate(c.created_at)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card>
            <Card
              title={isPrivileged(user) ? "Recent team activity" : "My recent activity"}
              className="lg:col-span-2"
              bodyClassName="px-4 py-1"
            >
              <ActivityList items={data.recent_activity} emptyText="No activity recorded yet" />
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
