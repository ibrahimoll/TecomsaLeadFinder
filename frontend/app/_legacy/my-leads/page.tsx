"use client";

import { Briefcase } from "lucide-react";
import { Suspense } from "react";

import { LeadStatusBadge, NextActivityText, SyncBadge } from "@/components/opportunity";
import { Avatar, DataTable, EmptyState, FilterPills, PageHeader, RowLink, Section } from "@/components/ui";
import { useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { useUrlState } from "@/lib/use-url-state";
import type { MyLead, SalesCounts } from "@/types";

type View = "" | "ready" | "due" | "overdue" | "meetings" | "proposals" | "opportunities" | "no_next";
const MATCH: Record<Exclude<View, "">, (l: MyLead) => boolean> = {
  ready: (l) => l.lead_status === "READY" && l.sync_status !== "SYNCED",
  due: (l) => l.due,
  overdue: (l) => Boolean(l.next_activity?.overdue),
  meetings: (l) => l.lead_status === "MEETING",
  proposals: (l) => l.lead_status === "PROPOSAL",
  opportunities: (l) => l.sync_status === "SYNCED",
  no_next: (l) => !l.next_activity && l.lead_status !== "WON" && l.lead_status !== "LOST",
};

/** What do I need to work today? (Managers / admins can switch to the team.) */
function MyLeadsView() {
  const privileged = isPrivileged(useCurrentUser());
  const [state, setState] = useUrlState(["view", "scope"] as const);
  const view = (state.view || "") as View;
  const team = privileged && state.scope === "team";
  const { data, error, loading, reload } = useApi<{ items: MyLead[]; counts: SalesCounts }>("/sales/my", { scope: team ? "team" : "mine" });
  const rows = data?.items.filter((l) => !view || MATCH[view](l));
  const c = data?.counts;
  const label = (text: string, n: number | undefined) => (n === undefined ? text : `${text} (${n})`);

  return (
    <Section flush>
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
        <FilterPills<string>
          label="Show"
          value={view}
          onChange={(v) => setState({ view: v })}
          options={[
            { value: "", label: label("All", data?.items.length) },
            { value: "ready", label: label("Ready", c?.ready), dot: "bg-info" },
            { value: "due", label: label("Follow-ups due", c?.due), dot: "bg-warning" },
            { value: "overdue", label: label("Overdue", c?.overdue), dot: "bg-danger" },
            { value: "meetings", label: label("Meetings", c?.meetings) },
            { value: "proposals", label: label("Proposals", c?.proposals) },
            { value: "opportunities", label: label("In Odoo", c?.opportunities), dot: "bg-success" },
            { value: "no_next", label: label("No next activity", c?.no_next_activity) },
          ]}
        />
        {privileged && (
          <span className="ml-auto">
            <FilterPills<string>
              label="Scope"
              value={team ? "team" : ""}
              onChange={(v) => setState({ scope: v })}
              options={[
                { value: "", label: "Mine" },
                { value: "team", label: "Team" },
              ]}
            />
          </span>
        )}
      </div>
      <DataTable<MyLead, number>
        caption="My leads"
        rows={rows}
        loading={loading}
        error={error?.message}
        onRetry={reload}
        rowKey={(r) => r.company_id}
        rowHref={(r) => `/companies/${r.company_id}`}
        empty={
          <EmptyState
            icon={<Briefcase />}
            title={view ? "Nothing here" : "No leads to work yet"}
            description="Qualified companies appear here, ready for an Odoo opportunity. Follow-ups you plan show up when they are due."
          />
        }
        columns={[
          {
            key: "name",
            header: "Company",
            cell: (r) => (
              <div className="min-w-[200px] max-w-[280px] py-1 leading-tight">
                <span className="block truncate"><RowLink href={`/companies/${r.company_id}`}>{r.name}</RowLink></span>
                <span className="block truncate text-[11.5px] text-fg-subtle">{r.title ?? r.city ?? "—"}</span>
              </div>
            ),
          },
          { key: "status", header: "Lead status", cell: (r) => <LeadStatusBadge value={r.lead_status} /> },
          { key: "odoo", header: "Odoo", cell: (r) => <SyncBadge value={r.sync_status} stage={r.odoo_stage} /> },
          { key: "next", header: "Next activity", cell: (r) => <span className="text-[12.5px]"><NextActivityText value={r.next_activity} /></span> },
          ...(team
            ? [{ key: "owner", header: "Salesperson", cell: (r: MyLead) => r.owner ? <span className="inline-flex items-center gap-2 text-fg-muted"><Avatar name={r.owner.name} size="sm" />{r.owner.name}</span> : <span className="text-fg-subtle">—</span> }]
            : []),
        ]}
      />
    </Section>
  );
}

export default function MyLeadsPage() {
  return (
    <>
      <PageHeader
        title="My leads"
        description="What to work today: qualified leads ready for Odoo, follow-ups due and open opportunities. Once a lead is in Odoo, its stage and won / lost come from Odoo."
      />
      <Suspense>
        <MyLeadsView />
      </Suspense>
    </>
  );
}
