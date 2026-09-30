"use client";

import clsx from "clsx";
import { ExternalLink, Pencil, ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import { useParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { ActivityList } from "@/components/activity-list";
import { CampaignStatusBadge, CrmStatusBadge, DivisionBadge, SourceBadge } from "@/components/status-badges";
import {
  Alert,
  Avatar,
  Badge,
  Button,
  ButtonLink,
  DataTable,
  DescriptionList,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  RowLink,
  Section,
  Select,
  Skeleton,
  Tabs,
  Textarea,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { SENIORITIES } from "@/lib/constants";
import { dash, formatDate, formatDateTime, formatMoney, location } from "@/lib/format";
import { useUrlState } from "@/lib/use-url-state";
import type { Activity, Campaign, CompanyDetail, Page } from "@/types";

type TabKey = "overview" | "relationship" | "intelligence" | "contacts" | "campaigns" | "activity";

// ---- Protection banner -------------------------------------------------------

function ProtectionBanner({ company }: { company: CompanyDetail }) {
  const status = company.odoo_status;
  const config = company.is_protected
    ? {
        icon: ShieldAlert,
        tone: "border-warning/30 bg-warning-soft",
        iconTone: "text-warning",
        title: "Protected: TECOMSA already has a relationship with this company",
        body: "Do not treat it as a new prospect. Coordinate with the owner below.",
      }
    : status === "AVAILABLE"
      ? {
          icon: ShieldCheck,
          tone: "border-success/25 bg-success-soft",
          iconTone: "text-success",
          title: "Available: no match in imported Odoo data",
          body: "This company can be considered for future LeadFinder processing.",
        }
      : {
          icon: ShieldQuestion,
          tone: "border-border bg-surface-muted",
          iconTone: "text-fg-muted",
          title: "Not checked yet",
          body: "No Odoo data has been imported, so LeadFinder cannot say whether TECOMSA already knows this company.",
        };
  const Icon = config.icon;
  return (
    <div className={clsx("mb-5 flex gap-3 rounded-lg border px-4 py-3", config.tone)} role="status">
      <Icon className={clsx("mt-0.5 h-4 w-4 shrink-0", config.iconTone)} aria-hidden />
      <div className="min-w-0 text-[13px]">
        <p className="font-medium text-fg">{config.title}</p>
        <p className="text-fg-muted">{config.body}</p>
        {company.crm_status_reason && status !== "NOT_CHECKED" && (
          <p className="mt-1 text-fg">
            <span className="text-fg-muted">Reason: </span>
            {company.crm_status_reason}
          </p>
        )}
      </div>
    </div>
  );
}

// ---- Tabs ----------------------------------------------------------------------

function OverviewTab({ company }: { company: CompanyDetail }) {
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
      <Section title="Company information" className="lg:col-span-2">
        <DescriptionList
          items={[
            { label: "Name", value: company.name },
            {
              label: "Website",
              value: company.website ? (
                <a href={company.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                  {company.domain ?? company.website} <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              ) : (
                "—"
              ),
            },
            { label: "Industry", value: dash(company.industry) },
            { label: "Company size", value: company.company_size ? `${company.company_size} employees` : "—" },
            { label: "Location", value: location(company.city, company.country) },
            { label: "Address", value: dash(company.address) },
            { label: "Phone", value: dash(company.main_phone) },
            { label: "Email", value: dash(company.main_email) },
            { label: "Source", value: <SourceBadge source={company.source} /> },
            { label: "Added", value: `${formatDate(company.created_at)} by ${company.creator?.name ?? "unknown"}` },
          ]}
        />
        {company.description && (
          <div className="mt-4 border-t border-border pt-3">
            <p className="text-xs text-fg-muted">Description</p>
            <p className="mt-0.5 whitespace-pre-line text-[13px]">{company.description}</p>
          </div>
        )}
      </Section>
      <div className="space-y-5">
        <Section title="Possible duplicates" flush>
          {company.possible_duplicates.length === 0 ? (
            <EmptyState compact title="No likely duplicates" description="Checked by domain, email domain, phone and name." />
          ) : (
            <ul className="divide-y divide-border">
              {company.possible_duplicates.map((d) => (
                <li key={d.company.id} className="px-4 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <RowLink href={`/companies/${d.company.id}`}>{d.company.name}</RowLink>
                    <CrmStatusBadge status={d.company.odoo_status} />
                  </div>
                  <p className="mt-0.5 text-xs text-fg-muted">{d.reason}</p>
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="Enrichment usage">
          <p className="text-[13px]">
            <span className="font-semibold tabular">{company.lusha_credits_used}</span>{" "}
            <span className="text-fg-muted">Lusha credits used. Lusha is not connected.</span>
          </p>
        </Section>
      </div>
    </div>
  );
}

function RelationshipTab({ company }: { company: CompanyDetail }) {
  const { crm_records, odoo_contacts, last_interaction } = company.relationship;
  const latest = crm_records[0];
  return (
    <div className="space-y-5">
      <Section title="TECOMSA relationship">
        <DescriptionList
          columns={3}
          items={[
            { label: "Status", value: <CrmStatusBadge status={company.odoo_status} /> },
            { label: "Owner (salesperson)", value: company.salesperson?.name ?? "—" },
            { label: "Current / last stage", value: latest ? dash(latest.stage) : "—" },
            { label: "Existing Odoo contact", value: odoo_contacts.length ? `Yes (${odoo_contacts.length})` : "No" },
            { label: "CRM leads / opportunities", value: crm_records.length ? String(crm_records.length) : "None" },
            { label: "Last interaction", value: formatDate(last_interaction) },
            { label: "Last checked", value: formatDateTime(company.crm_checked_at) },
          ]}
        />
      </Section>

      <Section title="CRM leads & opportunities" description="Imported from Odoo, matched by name, domain, email domain or phone." flush>
        <DataTable
          caption="CRM leads and opportunities"
          rows={crm_records}
          rowKey={(r) => r.id}
          empty={<EmptyState compact title="No CRM records match this company" />}
          columns={[
            {
              key: "name",
              header: "Opportunity",
              cell: (r) => (
                <div className="leading-tight">
                  <p className="font-medium">{r.opportunity_name}</p>
                  <p className="text-xs text-fg-muted">
                    {r.lead_type === "LEAD" ? "Lead" : "Opportunity"}
                    {r.odoo_lead_id ? ` · Odoo #${r.odoo_lead_id}` : ""}
                  </p>
                </div>
              ),
            },
            { key: "stage", header: "Stage", cell: (r) => dash(r.stage) },
            {
              key: "state",
              header: "State",
              cell: (r) =>
                r.is_won ? <Badge tone="accent" dot>Won</Badge> : r.is_lost ? <Badge tone="danger" dot>Lost</Badge> : <Badge tone="warning" dot>Open</Badge>,
            },
            { key: "owner", header: "Salesperson", cell: (r) => dash(r.salesperson_name) },
            { key: "rev", header: "Expected revenue", align: "right", cell: (r) => formatMoney(r.expected_revenue) },
            { key: "lost", header: "Lost reason", cell: (r) => <span className="text-fg-muted">{dash(r.lost_reason)}</span> },
            { key: "updated", header: "Last update", cell: (r) => <span className="text-fg-muted">{formatDate(r.updated_date ?? r.created_date)}</span> },
          ]}
        />
      </Section>

      <Section title="Odoo contacts" flush>
        <DataTable
          caption="Odoo contacts"
          rows={odoo_contacts}
          rowKey={(r) => r.id}
          empty={<EmptyState compact title="No Odoo contacts match this company" />}
          columns={[
            {
              key: "name",
              header: "Name",
              cell: (r) => (
                <div className="leading-tight">
                  <p className="font-medium">{r.contact_name}</p>
                  <p className="text-xs text-fg-muted">
                    {r.is_company ? "Company" : r.parent_company ? `Person at ${r.parent_company}` : "Person"}
                    {r.odoo_contact_id ? ` · Odoo #${r.odoo_contact_id}` : ""}
                  </p>
                </div>
              ),
            },
            { key: "email", header: "Email", cell: (r) => dash(r.email) },
            { key: "phone", header: "Phone", cell: (r) => dash(r.phone ?? r.mobile) },
            { key: "customer", header: "Customer", cell: (r) => (r.is_customer ? <Badge tone="accent">Customer</Badge> : "—") },
            { key: "owner", header: "Salesperson", cell: (r) => dash(r.salesperson_name) },
          ]}
        />
      </Section>
    </div>
  );
}

const INTELLIGENCE = [
  { label: "Odoo ERP fit", text: "How well Odoo ERP fits this company's operations." },
  { label: "Frinzo fit", text: "Fit for WhatsApp, Instagram and customer-messaging automation." },
  { label: "Company research", text: "Summary of the company's website and public information." },
  { label: "Recommended modules", text: "Suggested Odoo modules or Frinzo capabilities." },
  { label: "Decision-makers", text: "Relevant people to contact, found only when the company qualifies." },
  { label: "AI reasoning & confidence", text: "Why the company was or was not qualified, with a confidence level." },
];

function IntelligenceTab() {
  return (
    <Section
      title="LeadFinder intelligence"
      description="Populated from Phase 1 onwards. Nothing here is generated or estimated yet."
      flush
    >
      <ul className="divide-y divide-border">
        {INTELLIGENCE.map((item) => (
          <li key={item.label} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
            <div>
              <p className="text-[13px] font-medium">{item.label}</p>
              <p className="text-xs text-fg-muted">{item.text}</p>
            </div>
            <Badge>Not run yet</Badge>
          </li>
        ))}
      </ul>
    </Section>
  );
}

const EMPTY_CONTACT = {
  first_name: "",
  last_name: "",
  job_title: "",
  department: "",
  seniority: "",
  business_email: "",
  business_phone: "",
  linkedin_url: "",
};

function ContactForm({ companyId, onSaved, onCancel }: { companyId: number; onSaved: () => void; onCancel: () => void }) {
  const [values, setValues] = useState(EMPTY_CONTACT);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const set = (field: keyof typeof EMPTY_CONTACT) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [field]: e.target.value }));

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setErrors({});
    try {
      await api("/contacts", { method: "POST", body: { ...values, company_id: companyId } });
      onSaved();
    } catch (err) {
      setErrors(err instanceof ApiError ? { form: err.message, ...err.fieldErrors } : { form: "Could not save contact." });
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3 border-b border-border bg-surface-muted/50 p-4">
      {errors.form && <Alert>{errors.form}</Alert>}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <Field label="First name" htmlFor="first_name" required error={errors.first_name}>
          <Input id="first_name" value={values.first_name} onChange={set("first_name")} required maxLength={100} autoFocus />
        </Field>
        <Field label="Last name" htmlFor="last_name" error={errors.last_name}>
          <Input id="last_name" value={values.last_name} onChange={set("last_name")} maxLength={100} />
        </Field>
        <Field label="Job title" htmlFor="job_title" error={errors.job_title}>
          <Input id="job_title" value={values.job_title} onChange={set("job_title")} maxLength={200} />
        </Field>
        <Field label="Seniority" htmlFor="seniority" error={errors.seniority}>
          <Select id="seniority" value={values.seniority} onChange={set("seniority")}>
            <option value="">—</option>
            {SENIORITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Department" htmlFor="department" error={errors.department}>
          <Input id="department" value={values.department} onChange={set("department")} maxLength={100} />
        </Field>
        <Field label="Business email" htmlFor="business_email" error={errors.business_email}>
          <Input id="business_email" type="email" value={values.business_email} onChange={set("business_email")} maxLength={320} />
        </Field>
        <Field label="Business phone" htmlFor="business_phone" error={errors.business_phone}>
          <Input id="business_phone" type="tel" value={values.business_phone} onChange={set("business_phone")} maxLength={50} />
        </Field>
        <Field label="LinkedIn URL" htmlFor="linkedin_url" error={errors.linkedin_url}>
          <Input id="linkedin_url" value={values.linkedin_url} onChange={set("linkedin_url")} maxLength={500} placeholder="https://" />
        </Field>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save contact"}
        </Button>
      </div>
    </form>
  );
}

function ContactsTab({ company, onChanged }: { company: CompanyDetail; onChanged: () => void }) {
  const [adding, setAdding] = useState(false);
  return (
    <Section
      title="Contacts"
      description="People entered in LeadFinder. Odoo contacts are listed under TECOMSA relationship."
      flush
      actions={!adding && <Button variant="secondary" size="sm" onClick={() => setAdding(true)}>Add contact</Button>}
    >
      {adding && (
        <ContactForm
          companyId={company.id}
          onCancel={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            onChanged();
          }}
        />
      )}
      <DataTable
        caption="Contacts"
        rows={company.contacts}
        rowKey={(c) => c.id}
        empty={<EmptyState compact title="No contacts yet" description="Contacts are added manually in this version." />}
        columns={[
          {
            key: "name",
            header: "Name",
            cell: (c) => (
              <span className="font-medium">
                {c.full_name}
                {c.linkedin_url && (
                  <a href={c.linkedin_url} target="_blank" rel="noopener noreferrer" className="ml-2 text-xs font-normal text-accent hover:underline">
                    LinkedIn
                  </a>
                )}
              </span>
            ),
          },
          { key: "title", header: "Job title", cell: (c) => dash(c.job_title) },
          { key: "email", header: "Email", cell: (c) => dash(c.business_email) },
          { key: "phone", header: "Phone", cell: (c) => dash(c.business_phone) },
          { key: "source", header: "Source", cell: (c) => <Badge>{c.source === "MANUAL" ? "Manual" : c.source}</Badge> },
        ]}
      />
    </Section>
  );
}

function CampaignsTab({ company, onChanged }: { company: CompanyDetail; onChanged: () => void }) {
  const drafts = useApi<Page<Campaign>>("/campaigns", { status: "DRAFT", page_size: 100 });
  const ready = useApi<Page<Campaign>>("/campaigns", { status: "READY", page_size: 100 });
  const [campaignId, setCampaignId] = useState("");
  const [message, setMessage] = useState<{ tone: "danger" | "success"; text: string } | null>(null);
  const linked = new Set(company.campaigns.map((l) => l.campaign_id));
  const options = [...(drafts.data?.items ?? []), ...(ready.data?.items ?? [])].filter((c) => !linked.has(c.id));

  async function add() {
    setMessage(null);
    try {
      await api(`/campaigns/${campaignId}/companies/${company.id}`, { method: "POST" });
      setCampaignId("");
      setMessage({ tone: "success", text: "Company added to the campaign." });
      onChanged();
    } catch (err) {
      setMessage({ tone: "danger", text: err instanceof ApiError ? err.message : "Could not add to campaign." });
    }
  }

  return (
    <Section title="Campaigns" flush>
      <div className="space-y-2 border-b border-border px-4 py-3">
        <div className="flex max-w-xl gap-2">
          <Select value={campaignId} onChange={(e) => setCampaignId(e.target.value)} aria-label="Campaign to add this company to">
            <option value="">{options.length ? "Add to an open campaign…" : "No open campaigns available"}</option>
            {options.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Button onClick={add} disabled={!campaignId}>
            Add
          </Button>
        </div>
        {company.is_protected && (
          <p className="text-xs text-warning">This company is protected by an existing Odoo relationship. Coordinate with its owner before targeting it.</p>
        )}
        {message && <Alert tone={message.tone}>{message.text}</Alert>}
      </div>
      <DataTable
        caption="Campaigns containing this company"
        rows={company.campaigns}
        rowKey={(l) => l.campaign_id}
        empty={<EmptyState compact title="Not in any campaign" />}
        columns={[
          { key: "name", header: "Campaign", cell: (l) => <RowLink href={`/campaigns/${l.campaign_id}`}>{l.campaign_name}</RowLink> },
          { key: "div", header: "Division", cell: (l) => <DivisionBadge division={l.tecomsa_division} /> },
          { key: "status", header: "Campaign status", cell: (l) => <CampaignStatusBadge status={l.campaign_status} /> },
          { key: "added", header: "Added", cell: (l) => <span className="text-fg-muted">{formatDate(l.added_at)}</span> },
        ]}
      />
    </Section>
  );
}

function ActivityTab({ companyId }: { companyId: number }) {
  const activity = useApi<Page<Activity>>("/activities", { company_id: companyId, page_size: 50 });
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api(`/companies/${companyId}/notes`, { method: "POST", body: { notes } });
      setNotes("");
      await activity.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save note.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section title="Activity">
      <form onSubmit={onSubmit} className="mb-5 space-y-2">
        {error && <Alert>{error}</Alert>}
        <label htmlFor="note" className="sr-only">
          Add a note
        </label>
        <Textarea id="note" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Add a note…" maxLength={5000} className="min-h-[56px]" />
        <div className="flex justify-end">
          <Button type="submit" variant="secondary" size="sm" disabled={saving || !notes.trim()}>
            Add note
          </Button>
        </div>
      </form>
      {activity.error ? (
        <ErrorState message={activity.error.message} onRetry={activity.reload} />
      ) : (
        <ActivityList items={activity.data?.items} loading={activity.loading} />
      )}
    </Section>
  );
}

// ---- Page ------------------------------------------------------------------------

function CompanyProfile() {
  const { id } = useParams<{ id: string }>();
  const { data: company, error, loading, reload } = useApi<CompanyDetail>(`/companies/${id}`);
  const [state, setState] = useUrlState(["tab"] as const);
  const tab = (state.tab || "overview") as TabKey;

  if (error) return <Section><ErrorState message={error.message} onRetry={reload} /></Section>;
  if (loading && !company) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (!company) return null;

  const rel = company.relationship;
  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Companies", href: "/companies" }, { label: company.name }]}
        title={
          <span className="flex items-center gap-3">
            <Avatar name={company.name} size="lg" />
            <span className="min-w-0">
              <span className="block truncate">{company.name}</span>
            </span>
          </span>
        }
        meta={
          <>
            <CrmStatusBadge status={company.odoo_status} />
            {company.website && (
              <a href={company.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:text-accent">
                {company.domain} <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
            )}
            {company.industry && <span>{company.industry}</span>}
            <span>{location(company.city, company.country)}</span>
            <span>Owner: {company.salesperson?.name ?? "—"}</span>
          </>
        }
        actions={
          company.can_edit && (
            <ButtonLink href={`/companies/${company.id}/edit`} variant="secondary">
              <Pencil className="h-3.5 w-3.5" aria-hidden /> Edit
            </ButtonLink>
          )
        }
      />
      <ProtectionBanner company={company} />
      <div className="mb-4">
        <Tabs<TabKey>
          label="Company sections"
          value={tab}
          onChange={(key) => setState({ tab: key === "overview" ? "" : key })}
          tabs={[
            { key: "overview", label: "Overview" },
            { key: "relationship", label: "TECOMSA relationship", count: rel.crm_records.length + rel.odoo_contacts.length },
            { key: "intelligence", label: "Intelligence" },
            { key: "contacts", label: "Contacts", count: company.contacts.length },
            { key: "campaigns", label: "Campaigns", count: company.campaigns.length },
            { key: "activity", label: "Activity" },
          ]}
        />
      </div>
      <div role="tabpanel" tabIndex={0} className="focus-visible:outline-offset-4">
        {tab === "overview" && <OverviewTab company={company} />}
        {tab === "relationship" && <RelationshipTab company={company} />}
        {tab === "intelligence" && <IntelligenceTab />}
        {tab === "contacts" && <ContactsTab company={company} onChanged={reload} />}
        {tab === "campaigns" && <CampaignsTab company={company} onChanged={reload} />}
        {tab === "activity" && <ActivityTab companyId={company.id} />}
      </div>
    </>
  );
}

export default function CompanyProfilePage() {
  return (
    <Suspense>
      <CompanyProfile />
    </Suspense>
  );
}
