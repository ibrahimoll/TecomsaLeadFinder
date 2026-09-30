"use client";

import { ClipboardList } from "lucide-react";
import { Suspense, useCallback } from "react";

import { RequireCapability } from "@/components/guard";
import {
  Badge,
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
import { dash, formatDate, formatMoney } from "@/lib/format";
import { useDebouncedSearch, useUrlState } from "@/lib/use-url-state";
import type { CrmLead, OdooContact, Page, SalespersonRow } from "@/types";

type TabKey = "all" | "open" | "won" | "lost" | "contacts";
const PAGE_SIZE = 50;
const KEYS = ["tab", "q", "salesperson_id", "stage", "companies_only", "customers_only", "page"] as const;

function LeadState({ lead }: { lead: CrmLead }) {
  if (lead.is_won) return <Badge tone="accent" dot>Won</Badge>;
  if (lead.is_lost) return <Badge tone="danger" dot>Lost</Badge>;
  return <Badge tone="warning" dot>Open</Badge>;
}

function CompanyCell({ company, fallback }: { company: { id: number; name: string } | null; fallback: string | null }) {
  return company ? <RowLink href={`/companies/${company.id}`}>{company.name}</RowLink> : <span className="text-fg-muted">{dash(fallback)}</span>;
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
    salesperson_id: f.salesperson_id,
    companies_only: f.companies_only === "1" || undefined,
    customers_only: f.customers_only === "1" || undefined,
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
          onChange={(key) => setF({ tab: key === "all" ? "" : key, stage: "", companies_only: "", customers_only: "" })}
          tabs={[
            { key: "all", label: "All CRM records" },
            { key: "open", label: "Open" },
            { key: "won", label: "Customers (won)" },
            { key: "lost", label: "Lost" },
            { key: "contacts", label: "Odoo contacts" },
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
          <Select aria-label="Salesperson" className="w-44" value={f.salesperson_id} onChange={(e) => setF({ salesperson_id: e.target.value })}>
            <option value="">All salespeople</option>
            {salespeople.data?.map((s) => (
              <option key={s.salesperson.id} value={s.salesperson.id}>
                {s.salesperson.name}
              </option>
            ))}
          </Select>
          {tab === "contacts" ? (
            <>
              <Checkbox label="Companies only" checked={f.companies_only === "1"} onChange={(e) => setF({ companies_only: e.target.checked ? "1" : "" })} />
              <Checkbox label="Customers only" checked={f.customers_only === "1"} onChange={(e) => setF({ customers_only: e.target.checked ? "1" : "" })} />
            </>
          ) : (
            <Select aria-label="Stage" className="w-44" value={f.stage} onChange={(e) => setF({ stage: e.target.value })}>
              <option value="">All stages</option>
              {stages.data?.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
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
                  <div className="leading-tight">
                    <p className="font-medium">{r.contact_name}</p>
                    <p className="text-xs text-fg-muted">{r.is_company ? "Company" : r.parent_company ? `Person at ${r.parent_company}` : "Person"}</p>
                  </div>
                ),
              },
              { key: "company", header: "LeadFinder company", cell: (r) => <CompanyCell company={r.company} fallback={null} /> },
              { key: "email", header: "Email", cell: (r) => dash(r.email) },
              { key: "phone", header: "Phone", cell: (r) => dash(r.phone ?? r.mobile) },
              { key: "city", header: "City", cell: (r) => <span className="text-fg-muted">{dash(r.city)}</span> },
              { key: "customer", header: "Customer", cell: (r) => (r.is_customer ? <Badge tone="accent">Customer</Badge> : "—") },
              { key: "owner", header: "Salesperson", cell: (r) => dash(r.salesperson_name) },
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
                  <div className="max-w-[280px] leading-tight">
                    <p className="truncate font-medium" title={r.opportunity_name}>{r.opportunity_name}</p>
                    <p className="text-xs text-fg-muted">{r.lead_type === "LEAD" ? "Lead" : "Opportunity"}{r.odoo_lead_id ? ` · #${r.odoo_lead_id}` : ""}</p>
                  </div>
                ),
              },
              { key: "company", header: "Company", cell: (r) => <CompanyCell company={r.company} fallback={r.company_name} /> },
              { key: "stage", header: "Stage", cell: (r) => dash(r.stage) },
              { key: "state", header: "State", cell: (r) => <LeadState lead={r} /> },
              { key: "owner", header: "Salesperson", cell: (r) => dash(r.salesperson_name) },
              { key: "team", header: "Team", cell: (r) => <span className="text-fg-muted">{dash(r.sales_team)}</span> },
              { key: "rev", header: "Expected revenue", align: "right", cell: (r) => formatMoney(r.expected_revenue) },
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
