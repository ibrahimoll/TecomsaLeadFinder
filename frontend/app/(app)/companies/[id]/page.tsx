"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

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
  Field,
  Input,
  Loading,
  PageHeader,
  Select,
  Table,
  Td,
  Textarea,
  Th,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { SENIORITIES } from "@/lib/constants";
import { dash, formatDate, formatDateTime } from "@/lib/format";
import type { Activity, Campaign, CompanyDetail, Page } from "@/types";

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
    <form onSubmit={onSubmit} className="space-y-3 border-b border-slate-200 bg-slate-50 p-4">
      {errors.form && <Alert>{errors.form}</Alert>}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Field label="First name" htmlFor="first_name" required error={errors.first_name}>
          <Input id="first_name" value={values.first_name} onChange={set("first_name")} required maxLength={100} />
        </Field>
        <Field label="Last name" htmlFor="last_name" error={errors.last_name}>
          <Input id="last_name" value={values.last_name} onChange={set("last_name")} maxLength={100} />
        </Field>
        <Field label="Job title" htmlFor="job_title" error={errors.job_title}>
          <Input id="job_title" value={values.job_title} onChange={set("job_title")} maxLength={200} />
        </Field>
        <Field label="Department" htmlFor="department" error={errors.department}>
          <Input id="department" value={values.department} onChange={set("department")} maxLength={100} />
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
        <Field label="Business email" htmlFor="business_email" error={errors.business_email}>
          <Input id="business_email" type="email" value={values.business_email} onChange={set("business_email")} maxLength={320} />
        </Field>
        <Field label="Business phone" htmlFor="business_phone" error={errors.business_phone}>
          <Input id="business_phone" value={values.business_phone} onChange={set("business_phone")} maxLength={50} />
        </Field>
        <Field label="LinkedIn URL" htmlFor="linkedin_url" error={errors.linkedin_url} className="md:col-span-2">
          <Input id="linkedin_url" value={values.linkedin_url} onChange={set("linkedin_url")} maxLength={500} placeholder="https://www.linkedin.com/in/…" />
        </Field>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save contact"}
        </Button>
      </div>
    </form>
  );
}

function AddToCampaign({ company, onAdded }: { company: CompanyDetail; onAdded: () => void }) {
  // Draft/ready campaigns the current user can see; the backend re-checks permission.
  const drafts = useApi<Page<Campaign>>("/campaigns", { status: "DRAFT", page_size: 100 });
  const ready = useApi<Page<Campaign>>("/campaigns", { status: "READY", page_size: 100 });
  const [campaignId, setCampaignId] = useState("");
  const [message, setMessage] = useState<{ tone: "red" | "blue"; text: string } | null>(null);
  const linked = new Set(company.campaigns.filter((l) => l.status !== "REMOVED").map((l) => l.campaign_id));
  const options = [...(drafts.data?.items ?? []), ...(ready.data?.items ?? [])].filter((c) => !linked.has(c.id));

  async function add() {
    if (!campaignId) return;
    setMessage(null);
    try {
      await api(`/campaigns/${campaignId}/companies/${company.id}`, { method: "POST" });
      setCampaignId("");
      setMessage({ tone: "blue", text: "Company added to campaign." });
      onAdded();
    } catch (err) {
      setMessage({ tone: "red", text: err instanceof ApiError ? err.message : "Could not add to campaign." });
    }
  }

  return (
    <div className="space-y-2 border-b border-slate-200 p-3">
      <div className="flex gap-2">
        <Select value={campaignId} onChange={(e) => setCampaignId(e.target.value)} aria-label="Campaign">
          <option value="">{options.length ? "Select an open campaign…" : "No open campaigns available"}</option>
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
      {message && <Alert tone={message.tone}>{message.text}</Alert>}
    </div>
  );
}

function NoteForm({ companyId, onSaved }: { companyId: number; onSaved: () => void }) {
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
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save note.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-2 border-b border-slate-100 py-3">
      {error && <Alert>{error}</Alert>}
      <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Add a note…" maxLength={5000} className="min-h-[60px]" />
      <div className="flex justify-end">
        <Button type="submit" variant="secondary" disabled={saving || !notes.trim()}>
          Add note
        </Button>
      </div>
    </form>
  );
}

export default function CompanyProfilePage() {
  const { id } = useParams<{ id: string }>();
  const { data: company, error, loading, reload } = useApi<CompanyDetail>(`/companies/${id}`);
  const activity = useApi<Page<Activity>>("/activities", { company_id: id, page_size: 50 });
  const [addingContact, setAddingContact] = useState(false);

  const refreshAll = () => {
    void reload();
    void activity.reload();
  };

  if (loading && !company) return <Loading />;
  if (error) return <Alert>{error.message}</Alert>;
  if (!company) return null;

  return (
    <>
      <PageHeader
        title={company.name}
        description={`Added by ${company.creator?.name ?? "unknown user"} on ${formatDate(company.created_at)}`}
        actions={
          company.can_edit && (
            <ButtonLink href={`/companies/${company.id}/edit`} variant="secondary">
              Edit company
            </ButtonLink>
          )
        }
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card title="Company information">
            <DetailList
              items={[
                { label: "Name", value: company.name },
                {
                  label: "Website",
                  value: company.website ? (
                    <a href={company.website} target="_blank" rel="noopener noreferrer" className="text-brand-700 hover:underline">
                      {company.website}
                    </a>
                  ) : (
                    "—"
                  ),
                },
                { label: "Country", value: dash(company.country) },
                { label: "City", value: dash(company.city) },
                { label: "Industry", value: dash(company.industry) },
                { label: "Company size", value: company.company_size ? `${company.company_size} employees` : "—" },
                { label: "Phone", value: dash(company.main_phone) },
                { label: "Email", value: dash(company.main_email) },
              ]}
            />
            <div className="mt-4 border-t border-slate-100 pt-3">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Description</p>
              <p className="mt-1 whitespace-pre-line text-sm text-slate-800">{company.description || "—"}</p>
            </div>
          </Card>

          <Card
            title={`Contacts (${company.contacts.length})`}
            bodyClassName="p-0"
            actions={
              !addingContact && (
                <Button variant="secondary" onClick={() => setAddingContact(true)}>
                  Add contact
                </Button>
              )
            }
          >
            {addingContact && (
              <ContactForm
                companyId={company.id}
                onCancel={() => setAddingContact(false)}
                onSaved={() => {
                  setAddingContact(false);
                  refreshAll();
                }}
              />
            )}
            {company.contacts.length === 0 ? (
              <EmptyState title="No contacts yet" description="Contacts are added manually in this version." />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Name</Th>
                    <Th>Job title</Th>
                    <Th>Email</Th>
                    <Th>Phone</Th>
                    <Th>Source</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {company.contacts.map((ct) => (
                    <tr key={ct.id}>
                      <Td>
                        <span className="font-medium text-slate-900">{ct.full_name}</span>
                        {ct.linkedin_url && (
                          <a href={ct.linkedin_url} target="_blank" rel="noopener noreferrer" className="ml-2 text-xs text-brand-700 hover:underline">
                            LinkedIn
                          </a>
                        )}
                      </Td>
                      <Td>{dash(ct.job_title)}</Td>
                      <Td>{dash(ct.business_email)}</Td>
                      <Td>{dash(ct.business_phone)}</Td>
                      <Td>
                        <Badge>{ct.source === "MANUAL" ? "Manual" : ct.source}</Badge>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>

          <Card title="Activity history" bodyClassName="px-4 py-1">
            <NoteForm companyId={company.id} onSaved={refreshAll} />
            <ActivityList items={activity.data?.items ?? []} />
          </Card>
        </div>

        <div className="space-y-5">
          <Card title="CRM status">
            {company.odoo_status === "NOT_CHECKED" ? (
              <>
                <div className="flex items-center gap-2">
                  <Badge>NOT CHECKED</Badge>
                  <span className="text-sm font-medium text-slate-800">Not checked yet</span>
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  This company has not been checked against TECOMSA&apos;s Odoo CRM. Odoo verification will be
                  available in Phase 1.
                </p>
              </>
            ) : (
              <>
                <OdooStatusBadge status={company.odoo_status} />
                <p className="mt-2 text-xs text-slate-600">
                  Checked {formatDateTime(company.odoo_match?.checked_at)}
                  {company.odoo_match?.match_reason ? ` · ${company.odoo_match.match_reason}` : ""}
                </p>
              </>
            )}
          </Card>

          <Card title="Lusha usage">
            <p className="text-2xl font-semibold tabular-nums">{company.lusha_credits_used}</p>
            <p className="text-xs text-slate-500">credits used for this company · Lusha is not connected</p>
          </Card>

          <Card title={`Campaigns (${company.campaigns.length})`} bodyClassName="p-0">
            <AddToCampaign company={company} onAdded={refreshAll} />
            {company.campaigns.length === 0 ? (
              <EmptyState title="Not in any campaign" />
            ) : (
              <ul className="divide-y divide-slate-100">
                {company.campaigns.map((l) => (
                  <li key={l.campaign_id} className="space-y-1 px-4 py-2.5">
                    <Link href={`/campaigns/${l.campaign_id}`} className="text-sm font-medium text-brand-700 hover:underline">
                      {l.campaign_name}
                    </Link>
                    <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                      <DivisionBadge division={l.tecomsa_division} />
                      <CampaignStatusBadge status={l.campaign_status} />
                      <span>added {formatDate(l.added_at)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
