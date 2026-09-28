"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ActivityList } from "@/components/activity-list";
import { CampaignStatusBadge, DivisionBadge, OdooStatusBadge } from "@/components/status-badges";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  DetailList,
  EmptyState,
  Input,
  Loading,
  PageHeader,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { dash, formatDate, formatDateTime, sizeRange } from "@/lib/format";
import type { Activity, CampaignDetail, CampaignStatus, Company, Page } from "@/types";

function AddCompanyPanel({ campaignId, onAdded }: { campaignId: number; onAdded: () => void }) {
  const [q, setQ] = useState("");
  const [message, setMessage] = useState<{ tone: "red" | "blue"; text: string } | null>(null);
  const { data } = useApi<Page<Company>>(q.trim().length >= 2 ? "/companies" : null, { q, page_size: 8 });

  async function add(company: Company) {
    setMessage(null);
    try {
      await api(`/campaigns/${campaignId}/companies/${company.id}`, { method: "POST" });
      setMessage({ tone: "blue", text: `${company.name} added to the campaign.` });
      setQ("");
      onAdded();
    } catch (err) {
      setMessage({ tone: "red", text: err instanceof ApiError ? err.message : "Could not add company." });
    }
  }

  return (
    <div className="space-y-2">
      <Input placeholder="Search existing companies to add…" value={q} onChange={(e) => setQ(e.target.value)} />
      {message && <Alert tone={message.tone}>{message.text}</Alert>}
      {data && q.trim().length >= 2 && (
        <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
          {data.items.length === 0 && (
            <li className="px-3 py-2 text-sm text-slate-500">
              No matching company.{" "}
              <Link href="/companies/new" className="text-brand-700 hover:underline">
                Add it manually
              </Link>
            </li>
          )}
          {data.items.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span className="truncate text-sm">
                {c.name} <span className="text-slate-500">· {dash(c.country)}</span>
              </span>
              <Button variant="secondary" onClick={() => add(c)}>
                Add
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function CampaignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: c, error, loading, reload } = useApi<CampaignDetail>(`/campaigns/${id}`);
  const activity = useApi<Page<Activity>>("/activities", { campaign_id: id, page_size: 20 });
  const [statusError, setStatusError] = useState<string | null>(null);

  async function changeStatus(status: CampaignStatus) {
    setStatusError(null);
    try {
      await api(`/campaigns/${id}`, { method: "PATCH", body: { status } });
      await reload();
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.message : "Could not change status.");
    }
  }

  if (loading && !c) return <Loading />;
  if (error) return <Alert>{error.message}</Alert>;
  if (!c) return null;

  const open = c.status === "DRAFT" || c.status === "READY";

  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {c.name} <CampaignStatusBadge status={c.status} />
          </span>
        }
        description={`Created by ${c.creator.name} on ${formatDate(c.created_at)}`}
        actions={
          c.can_edit && (
            <>
              {c.status === "DRAFT" && (
                <>
                  <ButtonLink href={`/campaigns/${c.id}/edit`} variant="secondary">
                    Edit draft
                  </ButtonLink>
                  <Button onClick={() => changeStatus("READY")}>Mark ready</Button>
                </>
              )}
              {c.status === "READY" && (
                <Button variant="secondary" onClick={() => changeStatus("DRAFT")}>
                  Back to draft
                </Button>
              )}
              {open && (
                <Button variant="danger" onClick={() => changeStatus("CANCELLED")}>
                  Cancel campaign
                </Button>
              )}
            </>
          )
        }
      />
      {statusError && (
        <div className="mb-4">
          <Alert>{statusError}</Alert>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card title="Targeting">
            <DetailList
              items={[
                { label: "Division", value: <DivisionBadge division={c.tecomsa_division} /> },
                { label: "Country", value: c.country },
                { label: "Region", value: dash(c.region) },
                { label: "City", value: dash(c.city) },
                { label: "Industry", value: dash(c.industry) },
                { label: "Company size", value: sizeRange(c.company_size_min, c.company_size_max) },
                { label: "Target company count", value: c.target_company_count },
                {
                  label: "Target roles",
                  value: c.target_roles.length ? (
                    <span className="flex flex-wrap gap-1">
                      {c.target_roles.map((r) => (
                        <Badge key={r}>{r}</Badge>
                      ))}
                    </span>
                  ) : (
                    "—"
                  ),
                },
              ]}
            />
            {c.additional_instructions && (
              <div className="mt-4 border-t border-slate-100 pt-3">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Additional instructions</p>
                <p className="mt-1 whitespace-pre-line text-sm text-slate-800">{c.additional_instructions}</p>
              </div>
            )}
          </Card>

          <Card title={`Companies (${c.company_count} of ${c.target_company_count})`} bodyClassName="p-0">
            {c.can_edit && open && (
              <div className="border-b border-slate-200 p-3">
                <AddCompanyPanel
                  campaignId={c.id}
                  onAdded={() => {
                    void reload();
                    void activity.reload();
                  }}
                />
              </div>
            )}
            {c.companies.length === 0 ? (
              <EmptyState
                title="No companies in this campaign yet"
                description="Automatic company discovery is not available in this version. Add existing companies manually."
              />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Company</Th>
                    <Th>Country</Th>
                    <Th>Industry</Th>
                    <Th>Odoo status</Th>
                    <Th>Added</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {c.companies.map((link) => (
                    <tr key={link.id} className="hover:bg-slate-50">
                      <Td>
                        <Link href={`/companies/${link.company.id}`} className="font-medium text-brand-700 hover:underline">
                          {link.company.name}
                        </Link>
                      </Td>
                      <Td>{dash(link.company.country)}</Td>
                      <Td>{dash(link.company.industry)}</Td>
                      <Td>
                        <OdooStatusBadge status={link.company.odoo_status} />
                      </Td>
                      <Td>{formatDateTime(link.created_at)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>

        <div className="space-y-5">
          <Card title="Lusha usage">
            <p className="text-2xl font-semibold tabular-nums">{c.lusha_credits_used}</p>
            <p className="text-xs text-slate-500">
              credits used{c.max_lusha_credit_budget != null ? ` of ${c.max_lusha_credit_budget} budgeted` : ""}
            </p>
            <p className="mt-2 text-xs text-slate-500">Lusha is not connected. No credits are consumed.</p>
          </Card>
          <Card title="Activity" bodyClassName="px-4 py-1">
            <ActivityList items={activity.data?.items ?? []} />
          </Card>
        </div>
      </div>
    </>
  );
}
