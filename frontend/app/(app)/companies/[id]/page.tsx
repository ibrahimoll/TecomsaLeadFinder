"use client";

import clsx from "clsx";
import {
  Briefcase,
  Building2,
  CalendarDays,
  Database,
  ExternalLink,
  Globe,
  Linkedin,
  Mail,
  MapPin,
  Pencil,
  Phone,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  User,
  UserCheck,
} from "lucide-react";
import { useParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { ActivityList } from "@/components/activity-list";
import { CampaignStatusBadge, CrmStateBadge, CrmStatusBadge, DivisionBadge } from "@/components/status-badges";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  CopyButton,
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
        title: "Protected, do not treat as a new prospect",
        body: "TECOMSA already has a relationship with this company.",
      }
    : status === "AVAILABLE"
      ? {
          icon: ShieldCheck,
          tone: "border-success/25 bg-success-soft",
          iconTone: "text-success",
          title: "Available",
          body: "No match in imported Odoo data; this company can be considered for LeadFinder processing.",
        }
      : {
          icon: ShieldQuestion,
          tone: "border-border bg-surface-muted",
          iconTone: "text-fg-muted",
          title: "Not checked yet",
          body: "No Odoo data has been imported, so LeadFinder cannot say whether TECOMSA already knows this company.",
        };
  const Icon = config.icon;
  const reason = company.crm_status_reason && status !== "NOT_CHECKED" ? company.crm_status_reason : null;
  return (
    <div className={clsx("mb-4 flex gap-2.5 rounded border px-3 py-2 text-[13px]", config.tone)} role="status">
      <Icon className={clsx("mt-0.5 h-4 w-4 shrink-0", config.iconTone)} aria-hidden />
      <p className="min-w-0 text-fg">
        <span className="font-medium">{config.title}.</span>{" "}
        <span className="text-fg-muted">{reason ?? config.body}</span>
      </p>
    </div>
  );
}

// ---- Tabs ----------------------------------------------------------------------

/** Email / phone as an actionable link with copy-on-hover. */
function ContactValue({ kind, value }: { kind: "email" | "phone"; value: string | null }) {
  if (!value) return <>—</>;
  const href = kind === "email" ? `mailto:${value}` : `tel:${value.replace(/[^\d+]/g, "")}`;
  return (
    <>
      <a href={href} className={clsx("min-w-0 truncate hover:text-accent hover:underline", kind === "phone" && "tabular")}>
        {value}
      </a>
      <CopyButton value={value} label={kind} />
    </>
  );
}

function OverviewTab({ company }: { company: CompanyDetail }) {
  // The primary person: the first contact on file (imported or added in LeadFinder).
  const contact = company.contacts[0];
  const discovered = company.sources[0];
  const optional = [
    company.industry && { label: "Industry", value: company.industry },
    discovered?.category && { label: "Category", value: discovered.category.replace(/_/g, " ").replace(/^\w/, (ch) => ch.toUpperCase()) },
    discovered && {
      label: "Discovered",
      value: `${formatDate(discovered.first_seen_at)}${discovered.first_seen_run_id ? ` · search #${discovered.first_seen_run_id}` : ""}`,
    },
    company.company_size && { label: "Company size", value: `${company.company_size} employees` },
    company.address && { label: "Address", value: company.address },
  ].filter(Boolean) as { label: string; value: string }[];
  const dupes = company.possible_duplicates;
  const email = company.main_email ?? contact?.business_email ?? null;
  const phone = company.main_phone ?? contact?.business_phone ?? null;
  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="px-5 py-3">
        <DescriptionList
          inline
          items={[
            { label: "Company", icon: <Building2 />, value: <span className="font-medium">{company.name}</span> },
            { label: "Contact", icon: <User />, value: dash(contact?.full_name) },
            { label: "Position", icon: <Briefcase />, value: dash(contact?.job_title) },
            { label: "Email", icon: <Mail />, value: <ContactValue kind="email" value={email} /> },
            { label: "Phone", icon: <Phone />, value: <ContactValue kind="phone" value={phone} /> },
            {
              label: "Website",
              icon: <Globe />,
              value: company.website ? (
                <a href={company.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                  {company.domain ?? company.website} <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              ) : (
                "—"
              ),
            },
            {
              label: "LinkedIn",
              icon: <Linkedin />,
              value: contact?.linkedin_url ? (
                <a href={contact.linkedin_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                  {contact.full_name} <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              ) : (
                "—"
              ),
            },
            { label: "Location", icon: <MapPin />, value: location(company.city, company.country) },
            { label: "Relationship", icon: <ShieldCheck />, value: <CrmStatusBadge status={company.odoo_status} /> },
            { label: "Owner", icon: <UserCheck />, value: company.salesperson?.name ?? "—" },
            {
              label: "Source",
              icon: <Database />,
              value:
                company.sources.length > 1 ? company.sources.map((s) => s.source_label).join(", ") : company.source_label,
            },
            { label: "Added", icon: <CalendarDays />, value: `${formatDate(company.created_at)} · ${company.creator?.name ?? "unknown"}` },
            ...optional,
          ]}
        />
        {company.description && (
          <div className="mt-2 grid grid-cols-[8.5rem_minmax(0,1fr)] gap-x-4 border-t border-border pt-3 text-[13px]">
            <span className="text-fg-muted">Description</span>
            <p className="whitespace-pre-line">{company.description}</p>
          </div>
        )}
      </div>
      <div className="border-t border-border px-5 py-2.5 text-[13px]">
        {dupes.length === 0 ? (
          <p className="text-fg-muted">No likely duplicates found. Checked by domain, email domain, phone and name.</p>
        ) : (
          <>
            <p className="font-medium text-fg">Possible duplicates ({dupes.length})</p>
            <ul className="mt-1 divide-y divide-border">
              {dupes.map((d) => (
                <li key={d.company.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
                  <RowLink href={`/companies/${d.company.id}`}>{d.company.name}</RowLink>
                  <CrmStatusBadge status={d.company.odoo_status} />
                  <span className="text-xs text-fg-muted">{d.reason}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
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
                <CrmStateBadge lead={r} />,
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
                    {r.is_company ? "Company record" : "Contact"}
                    {r.odoo_contact_id ? ` · Odoo #${r.odoo_contact_id}` : ""}
                  </p>
                </div>
              ),
            },
            { key: "position", header: "Position", cell: (r) => <span className="text-fg-muted">{dash(r.job_position)}</span> },
            { key: "phone", header: "Phone", cell: (r) => <span className="tabular">{dash(r.mobile ?? r.phone)}</span> },
            { key: "email", header: "Email", cell: (r) => dash(r.email) },
            { key: "loc", header: "Location", cell: (r) => <span className="text-fg-muted">{location(r.city, r.country)}</span> },
          ]}
        />
      </Section>
    </div>
  );
}

const CONTACT_SOURCE_LABEL: Record<string, string> = { MANUAL: "Manual", ODOO_IMPORT: "Odoo contact import" };

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
      description="Company research has not been run yet. Nothing here is generated or estimated."
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
      description="People at this company: imported from Odoo contacts or added in LeadFinder."
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
        empty={
          <EmptyState
            compact
            title="No contacts yet"
            description="Import an Odoo contacts export, or add a contact manually."
          />
        }
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
          { key: "source", header: "Source", cell: (c) => <span className="text-fg-muted">{CONTACT_SOURCE_LABEL[c.source] ?? c.source}</span> },
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
        title={company.name}
        meta={
          <>
            <CrmStatusBadge status={company.odoo_status} />
            {company.website && (
              <a href={company.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:text-accent">
                {company.domain} <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
            )}
            {company.industry && <span>{company.industry}</span>}
            <span>
              {location(company.city, company.country)} · Owner: {company.salesperson?.name ?? "—"}
            </span>
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
            { key: "contacts", label: "LeadFinder contacts", count: company.contacts.length },
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
