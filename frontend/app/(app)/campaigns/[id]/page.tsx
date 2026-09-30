"use client";

import { Pencil } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ActivityList } from "@/components/activity-list";
import { CampaignStatusBadge, CrmStatusBadge, DivisionBadge } from "@/components/status-badges";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  ConfirmDialog,
  DataTable,
  DescriptionList,
  EmptyState,
  ErrorState,
  PageHeader,
  RowLink,
  SearchInput,
  Section,
  Skeleton,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { dash, formatDate, formatDateTime, location, sizeRange } from "@/lib/format";
import type { Activity, CampaignDetail, CampaignStatus, Company, Page } from "@/types";

function AddCompanyPanel({ campaignId, onAdded }: { campaignId: number; onAdded: () => void }) {
  const [q, setQ] = useState("");
  const [message, setMessage] = useState<{ tone: "danger" | "success"; text: string } | null>(null);
  const { data } = useApi<Page<Company>>(q.trim().length >= 2 ? "/companies" : null, { q, page_size: 8 });

  async function add(company: Company) {
    setMessage(null);
    try {
      await api(`/campaigns/${campaignId}/companies/${company.id}`, { method: "POST" });
      setMessage({ tone: "success", text: `${company.name} added to the campaign.` });
      setQ("");
      onAdded();
    } catch (err) {
      setMessage({ tone: "danger", text: err instanceof ApiError ? err.message : "Could not add company." });
    }
  }

  return (
    <div className="space-y-2 border-b border-border px-4 py-3">
      <SearchInput value={q} onChange={setQ} placeholder="Search existing companies to add" label="Search companies to add" className="max-w-md" />
      {message && <Alert tone={message.tone}>{message.text}</Alert>}
      {data && q.trim().length >= 2 && (
        <ul className="max-w-2xl divide-y divide-border rounded border border-border">
          {data.items.length === 0 && (
            <li className="px-3 py-2 text-[13px] text-fg-muted">
              No matching company.{" "}
              <Link href="/companies/new" className="text-accent hover:underline">
                Add it manually
              </Link>
            </li>
          )}
          {data.items.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span className="flex min-w-0 items-center gap-2 text-[13px]">
                <span className="truncate font-medium">{c.name}</span>
                <CrmStatusBadge status={c.odoo_status} />
              </span>
              <Button variant="secondary" size="sm" onClick={() => add(c)}>
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
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [busy, setBusy] = useState(false);

  async function changeStatus(status: CampaignStatus) {
    setStatusError(null);
    setBusy(true);
    try {
      await api(`/campaigns/${id}`, { method: "PATCH", body: { status } });
      await reload();
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.message : "Could not change status.");
    } finally {
      setBusy(false);
      setConfirmCancel(false);
    }
  }

  if (error) return <Section><ErrorState message={error.message} onRetry={reload} /></Section>;
  if (loading && !c) return <Skeleton className="h-64 w-full" />;
  if (!c) return null;

  const open = c.status === "DRAFT" || c.status === "READY";
  const protectedCount = c.companies.filter((l) => !["AVAILABLE", "NOT_CHECKED"].includes(l.company.odoo_status)).length;

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Campaigns", href: "/campaigns" }, { label: c.name }]}
        title={c.name}
        meta={
          <>
            <CampaignStatusBadge status={c.status} />
            <DivisionBadge division={c.tecomsa_division} />
            <span>
              Created by {c.creator.name} on {formatDate(c.created_at)}
            </span>
          </>
        }
        actions={
          c.can_edit && (
            <>
              {c.status === "DRAFT" && (
                <>
                  <ButtonLink href={`/campaigns/${c.id}/edit`} variant="secondary">
                    <Pencil className="h-3.5 w-3.5" aria-hidden /> Edit draft
                  </ButtonLink>
                  <Button onClick={() => changeStatus("READY")} disabled={busy}>
                    Mark ready
                  </Button>
                </>
              )}
              {c.status === "READY" && (
                <Button variant="secondary" onClick={() => changeStatus("DRAFT")} disabled={busy}>
                  Back to draft
                </Button>
              )}
              {open && (
                <Button variant="danger" onClick={() => setConfirmCancel(true)} disabled={busy}>
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

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <div className="space-y-5 xl:col-span-2">
          <Section title="Targeting">
            <DescriptionList
              columns={3}
              items={[
                { label: "Market", value: [c.city, c.region, c.country].filter(Boolean).join(", ") },
                { label: "Industry", value: dash(c.industry) },
                { label: "Company size", value: sizeRange(c.company_size_min, c.company_size_max) },
                { label: "Target companies", value: c.target_company_count },
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
                { label: "Lusha budget", value: c.max_lusha_credit_budget != null ? `${c.lusha_credits_used} / ${c.max_lusha_credit_budget} credits` : `${c.lusha_credits_used} credits used` },
              ]}
            />
            {c.additional_instructions && (
              <div className="mt-4 border-t border-border pt-3">
                <p className="text-xs text-fg-muted">Additional instructions</p>
                <p className="mt-0.5 whitespace-pre-line text-[13px]">{c.additional_instructions}</p>
              </div>
            )}
          </Section>

          <Section
            title={`Companies · ${c.company_count} of ${c.target_company_count}`}
            description={protectedCount ? `${protectedCount} already known in Odoo; coordinate with their owners.` : undefined}
            flush
          >
            {c.can_edit && open && (
              <AddCompanyPanel
                campaignId={c.id}
                onAdded={() => {
                  void reload();
                  void activity.reload();
                }}
              />
            )}
            <DataTable
              caption="Companies in this campaign"
              rows={c.companies}
              rowKey={(l) => l.id}
              empty={
                <EmptyState
                  compact
                  title="No companies in this campaign yet"
                  description="Automatic discovery arrives in a later phase. Add existing companies above."
                />
              }
              columns={[
                { key: "name", header: "Company", cell: (l) => <RowLink href={`/companies/${l.company.id}`}>{l.company.name}</RowLink> },
                { key: "loc", header: "Country", cell: (l) => <span className="text-fg-muted">{location(null, l.company.country)}</span> },
                { key: "industry", header: "Industry", cell: (l) => <span className="text-fg-muted">{dash(l.company.industry)}</span> },
                { key: "crm", header: "CRM status", cell: (l) => <CrmStatusBadge status={l.company.odoo_status} /> },
                { key: "added", header: "Added", cell: (l) => <span className="text-fg-muted">{formatDateTime(l.created_at)}</span> },
              ]}
            />
          </Section>
        </div>

        <Section title="Activity">
          {activity.error ? (
            <ErrorState message={activity.error.message} onRetry={activity.reload} />
          ) : (
            <ActivityList items={activity.data?.items} loading={activity.loading} />
          )}
        </Section>
      </div>

      <ConfirmDialog
        open={confirmCancel}
        title="Cancel this campaign?"
        confirmLabel="Cancel campaign"
        tone="danger"
        busy={busy}
        onConfirm={() => changeStatus("CANCELLED")}
        onClose={() => setConfirmCancel(false)}
      >
        A cancelled campaign cannot be edited or reopened. Its companies stay in the company database.
      </ConfirmDialog>
    </>
  );
}
