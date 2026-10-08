"use client";

import { CircleDot, ClipboardList, Contact, Layers, Trophy, XCircle } from "lucide-react";
import { Suspense, useCallback } from "react";

import { RequireCapability } from "@/components/guard";
import { CrmStateBadge } from "@/components/status-badges";
import {
  Avatar,
  ButtonLink,
  Checkbox,
  DataTable,
  EmptyState,
  PageHeader,
  Pagination,
  RowLink,
  SearchInput,
  Section,
  Select,
  Tabs,
  Toolbar,
} from "@/components/ui";
import { useApi } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth";
import { dash, formatDate, formatMoney, location } from "@/lib/format";
import { useDebouncedSearch, useUrlState } from "@/lib/use-url-state";
import type { CrmLead, OdooContact, Page, SalespersonRow } from "@/types";

type TabKey = "all" | "open" | "won" | "lost" | "contacts";
const PAGE_SIZE = 50;
const KEYS = ["tab", "q", "salesperson_id", "stage", "companies_only", "page"] as const;

function CompanyCell({ company, fallback }: { company: { id: number; name: string } | null; fallback: string | null }) {
  const name = company?.name ?? fallback;
  if (!name) return <span className="text-fg-subtle">—</span>;
  return (
    <span className="inline-flex max-w-[240px] items-center gap-2">
      <Avatar name={name} size="sm" />
      {company ? <RowLink href={`/companies/${company.id}`}>{company.name}</RowLink> : <span className="truncate text-fg-muted">{name}</span>}
    </span>
  );
}

function Person({ name }: { name: string | null }) {
  if (!name) return <span className="text-fg-subtle">—</span>;
  return (
    <span className="inline-flex items-center gap-2 text-fg-muted">
      <Avatar name={name} size="sm" /> {name}
    </span>
  );
}

function CrmView() {
  const user = useCurrentUser();
  const [f, setF] = useUrlState(KEYS);
  const tab = (f.tab || "all") as TabKey;
  const page = Number(f.page) || 1;
  const commitSearch = useCallback((q: string) => setF({ q }), [setF]);
  const [search, setSearch] = useDebouncedSearch(f.q, commitSearch);
  const salespeople = useApi<SalespersonRow[]>("/salespeople");
  const stages = useApi<string[]>(tab === "contacts" ? null : "/odoo/stages");

  const leads = useApi<Page<CrmLead>>(tab === "contacts" ? null : "/odoo/leads", {
    state: tab === "all" ? undefined : tab,
    q: f.q,
    salesperson_id: f.salesperson_id,
    stage: f.stage,
    page,
    page_size: PAGE_SIZE,
  });
  const contacts = useApi<Page<OdooContact>>(tab === "contacts" ? "/odoo/contacts" : null, {
    q: f.q,
    companies_only: f.companies_only === "1" || undefined,
    page,
    page_size: PAGE_SIZE,
  });
  const active = tab === "contacts" ? contacts : leads;
  const empty = (
    <EmptyState
      icon={<ClipboardList className="h-5 w-5" />}
      title={f.q || f.salesperson_id || f.stage ? "No records match these filters" : "No Odoo records imported"}
      description={f.q ? undefined : "Import Odoo CRM and contact exports to populate this view."}
      action={user.capabilities.run_imports && !f.q && <ButtonLink href="/data-sources/odoo" size="sm">Import from Odoo</ButtonLink>}
    />
  );

  return (
    <>
      <div className="mb-4">
        <Tabs<TabKey>
          label="CRM record types"
          value={tab}
          onChange={(key) => setF({ tab: key === "all" ? "" : key, stage: "", companies_only: "", salesperson_id: "" })}
          tabs={[
            { key: "all", label: "All CRM records", icon: Layers },
            { key: "open", label: "Open", icon: CircleDot },
            { key: "won", label: "Customers (won)", icon: Trophy },
            { key: "lost", label: "Lost", icon: XCircle },
            { key: "contacts", label: "Odoo contacts", icon: Contact },
          ]}
        />
      </div>
      <Section flush>
        <Toolbar>
          <SearchInput
            className="w-full sm:w-72"
            value={search}
            onChange={setSearch}
            placeholder={tab === "contacts" ? "Search name, company, email" : "Search opportunity, customer, email"}
            label="Search CRM records"
          />
          {tab === "contacts" ? (
            <Checkbox label="Company records only" checked={f.companies_only === "1"} onChange={(e) => setF({ companies_only: e.target.checked ? "1" : "" })} />
          ) : (
            <>
            <Select aria-label="Salesperson" className="w-44" value={f.salesperson_id} onChange={(e) => setF({ salesperson_id: e.target.value })}>
              <option value="">All salespeople</option>
              {salespeople.data?.map((s) => (
                <option key={s.salesperson.id} value={s.salesperson.id}>
                  {s.salesperson.name}
                </option>
              ))}
            </Select>
            <Select aria-label="Stage" className="w-44" value={f.stage} onChange={(e) => setF({ stage: e.target.value })}>
              <option value="">All stages</option>
              {stages.data?.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
            </>
          )}
          {active.data && (
            <span className="ml-auto self-center text-xs text-fg-muted">
              <span className="font-semibold tabular text-fg">{active.data.total.toLocaleString()}</span> {active.data.total === 1 ? "record" : "records"}
            </span>
          )}
        </Toolbar>

        {tab === "contacts" ? (
          <DataTable
            caption="Odoo contacts"
            rows={contacts.data?.items}
            loading={contacts.loading}
            error={contacts.error?.message}
            onRetry={contacts.reload}
            rowKey={(r) => r.id}
            empty={empty}
            columns={[
              {
                key: "name",
                header: "Name",
                cell: (r) => (
                  <div className="flex items-center gap-2.5 py-1">
                    <Avatar name={r.contact_name} size="sm" />
                    <div className="leading-tight">
                      <p className="font-medium">{r.contact_name}</p>
                      <p className="text-xs text-fg-muted">{r.is_company ? "Company record" : "Contact"}</p>
                    </div>
                  </div>
                ),
              },
              { key: "position", header: "Position", cell: (r) => <span className="text-fg-muted">{dash(r.job_position)}</span> },
              { key: "company", header: "Company", cell: (r) => <CompanyCell company={r.company} fallback={r.is_company ? null : r.parent_company} /> },
              {
                key: "phone",
                header: "Phone",
                cell: (r) => {
                  const phone = r.mobile ?? r.phone;
                  return phone ? (
                    <a href={`tel:${phone.replace(/[^\d+]/g, "")}`} className="tabular hover:text-accent hover:underline">
                      {phone}
                    </a>
                  ) : (
                    <span className="text-fg-subtle">—</span>
                  );
                },
              },
              {
                key: "email",
                header: "Email",
                cell: (r) =>
                  r.email ? (
                    <a href={`mailto:${r.email}`} className="hover:text-accent hover:underline">
                      {r.email}
                    </a>
                  ) : (
                    <span className="text-fg-subtle">—</span>
                  ),
              },
              { key: "loc", header: "Location", cell: (r) => <span className="text-fg-muted">{location(r.city, r.country)}</span> },
              { key: "id", header: "Odoo ID", align: "right", cell: (r) => <span className="text-fg-muted">{r.odoo_contact_id ?? "—"}</span> },
            ]}
          />
        ) : (
          <DataTable
            caption="CRM leads and opportunities"
            rows={leads.data?.items}
            loading={leads.loading}
            error={leads.error?.message}
            onRetry={leads.reload}
            rowKey={(r) => r.id}
            empty={empty}
            columns={[
              {
                key: "name",
                header: "Opportunity",
                cell: (r) => (
                  <div className="max-w-[300px] py-1">
                    <div className="min-w-0 leading-tight">
                      <p className="truncate font-medium" title={r.opportunity_name}>{r.opportunity_name}</p>
                      <p className="text-xs text-fg-muted">{r.lead_type === "LEAD" ? "Lead" : "Opportunity"}{r.odoo_lead_id ? ` · #${r.odoo_lead_id}` : ""}</p>
                    </div>
                  </div>
                ),
              },
              { key: "company", header: "Company", cell: (r) => <CompanyCell company={r.company} fallback={r.company_name} /> },
              {
                key: "stage",
                header: "Stage",
                cell: (r) =>
                  r.stage ? (
                    <span className="rounded-full border border-border bg-surface-muted/60 px-2 py-0.5 text-xs font-medium text-fg">{r.stage}</span>
                  ) : (
                    <span className="text-fg-subtle">—</span>
                  ),
              },
              { key: "state", header: "State", cell: (r) => <CrmStateBadge lead={r} /> },
              { key: "owner", header: "Salesperson", cell: (r) => <Person name={r.salesperson_name} /> },
              { key: "team", header: "Team", cell: (r) => <span className="text-fg-muted">{dash(r.sales_team)}</span> },
              {
                key: "rev",
                header: "Expected revenue",
                align: "right",
                cell: (r) => <span className={r.expected_revenue ? "font-semibold text-fg" : "text-fg-subtle"}>{formatMoney(r.expected_revenue)}</span>,
              },
              { key: "lost", header: "Lost reason", cell: (r) => <span className="text-fg-muted">{dash(r.lost_reason)}</span> },
              { key: "updated", header: "Last update", cell: (r) => <span className="text-fg-muted">{formatDate(r.updated_date ?? r.created_date)}</span> },
            ]}
          />
        )}
        {active.data && (
          <div className="border-t border-border">
            <Pagination page={page} pageSize={PAGE_SIZE} total={active.data.total} onPage={(p) => setF({ page: String(p) })} />
          </div>
        )}
      </Section>
    </>
  );
}

export default function CrmRecordsPage() {
  return (
    <RequireCapability capability="view_crm">
      <PageHeader
        title="CRM records"
        description="Imported Odoo data that protects companies from being treated as new prospects."
      />
      <Suspense>
        <CrmView />
      </Suspense>
    </RequireCapability>
  );
}
