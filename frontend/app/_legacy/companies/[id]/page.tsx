"use client";

import clsx from "clsx";
import { Activity as ActivityIcon, Contact, Copy, Navigation, Radar, type LucideIcon, Briefcase, Building2, CalendarDays, ChevronRight, Handshake, LayoutGrid, Megaphone, Sparkles, Users, Check, Database, ExternalLink, Globe, Linkedin, Mail, MapPin, Minus, Pencil, Phone, Plus, Save, ShieldAlert, ShieldCheck, ShieldQuestion, StickyNote, User, UserCheck, Search } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent, type ReactNode } from "react";

import { ActivityList } from "@/components/activity-list";
import { CompanyDecisionMakers } from "@/components/company-decision-makers";
import { CompanyIntelligence } from "@/components/company-intelligence";
import { OpportunityCard, OpportunityModal, useOpportunity } from "@/components/opportunity";
import { ResearchModal } from "@/components/research-modal";
import { ResearchSummary } from "@/components/research-summary";
import { CampaignStatusBadge, ConfidenceBadge, CrmStateBadge, CrmStatusBadge, DivisionBadge } from "@/components/status-badges";
import { Alert, Avatar, Badge, Button, CopyButton, CountUp, DataTable, DescriptionList, EmptyState, ErrorState, Field, Input, RowLink, Section, Select, Skeleton, Tabs, Textarea, toast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { SENIORITIES } from "@/lib/constants";
import { dash, formatDate, formatDateTime, formatMoney, location } from "@/lib/format";
import { rememberCompany } from "@/lib/recent";
import { useUrlState } from "@/lib/use-url-state";
import type { Activity, Campaign, CompanyDetail, Page } from "@/types";
import { safeHref } from "@/lib/url";

type TabKey = "overview" | "locations" | "relationship" | "intelligence" | "people" | "contacts" | "campaigns" | "activity";

// ---- Protection banner -------------------------------------------------------

function ProtectionStrip({ company }: { company: CompanyDetail }) {
  const status = company.odoo_status;
  const config = company.is_protected
    ? {
        icon: ShieldAlert,
        light: "bg-warning",
        title: "Protected, do not treat as a new prospect",
        body: "TECOMSA already has a relationship with this company.",
      }
    : status === "AVAILABLE"
      ? {
          icon: ShieldCheck,
          light: "bg-success",
          title: "Available",
          body: "No match in TECOMSA's imported Odoo data. You can approach this company as a new prospect.",
        }
      : {
          icon: ShieldQuestion,
          light: "bg-white/70",
          title: "Not checked yet",
          body: "No Odoo data has been imported, so LeadFinder cannot say whether TECOMSA already knows this company.",
        };
  const Icon = config.icon;
  const reason = company.crm_status_reason && status !== "NOT_CHECKED" ? company.crm_status_reason : null;
  return (
    <div className="relative flex items-center gap-3 border-t border-white/15 bg-black/15 px-6 py-3 text-[13px] backdrop-blur-sm md:px-8" role="status">
      {/* Status light: the relationship state at a glance (static; it is not in-progress work). */}
      <span className="relative flex h-2.5 w-2.5 shrink-0" aria-hidden>
        <span className={clsx("relative h-2.5 w-2.5 rounded-full ring-2 ring-white/30", config.light)} />
      </span>
      <Icon className="h-4 w-4 shrink-0 text-white/80" aria-hidden />
      <p className="min-w-0 text-white">
        <span className="font-semibold">{config.title}.</span> <span className="text-white/75">{reason ?? config.body}</span>
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

/** A titled card for the Overview grid. */
function InfoCard({ title, icon: Icon, children, className }: { title: string; icon: LucideIcon; children: ReactNode; className?: string }) {
  return (
    <section className={clsx("rounded-lg border border-border bg-surface shadow-card", className)}>
      <h3 className="flex items-center gap-2 border-b border-border px-4 py-3 text-[14px] font-semibold">
        <Icon className="h-4 w-4 text-fg-subtle" aria-hidden />
        {title}
      </h3>
      <div className="p-4">{children}</div>
    </section>
  );
}

/** Icon + label over the value; the row highlights on hover and shows copy buttons. */
function InfoRow({ icon: Icon, label, children }: { icon: LucideIcon; label: string; children: ReactNode }) {
  return (
    <div className="group -mx-2 flex gap-3 rounded-md px-2 py-2 transition-colors hover:bg-surface-hover/60">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-fg-subtle transition-colors group-hover:text-accent" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-fg-subtle">{label}</p>
        <div className="mt-0.5 flex min-w-0 items-center gap-1 break-words text-[13px] text-fg">{children}</div>
      </div>
    </div>
  );
}

function OverviewTab({ company }: { company: CompanyDetail }) {
  // The primary person: the first contact on file (imported or added in LeadFinder).
  const contact = company.contacts[0];
  const discovered = company.sources[0];
  const dupes = company.possible_duplicates;
  const email = company.main_email ?? contact?.business_email ?? null;
  const phone = company.main_phone ?? contact?.business_phone ?? null;
  const ev = company.discovery_evidence;
  const link = "inline-flex min-w-0 items-center gap-1 text-accent hover:underline";
  return (
    <div className="stagger space-y-4">
      <div className="stagger grid gap-4 lg:grid-cols-3">
        <InfoCard title="Contact" icon={User}>
          {contact ? (
            <div className="mb-2 flex items-center gap-3">
              <Avatar name={contact.full_name} size="lg" />
              <div className="min-w-0">
                <p className="truncate font-display text-[15px] font-semibold">{contact.full_name}</p>
                <p className="truncate text-xs text-fg-muted">{contact.job_title ?? "Position unknown"}</p>
              </div>
            </div>
          ) : (
            <p className="mb-2 text-[13px] text-fg-muted">No contact person on file yet.</p>
          )}
          <InfoRow icon={Mail} label="Email">
            <ContactValue kind="email" value={email} />
          </InfoRow>
          <InfoRow icon={Phone} label="Phone">
            <ContactValue kind="phone" value={phone} />
          </InfoRow>
          {contact?.linkedin_url && (
            <InfoRow icon={Linkedin} label="LinkedIn">
              <a href={safeHref(contact.linkedin_url)} target="_blank" rel="noopener noreferrer" className={link}>
                <span className="truncate">{contact.full_name}</span> <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
              </a>
            </InfoRow>
          )}
        </InfoCard>

        <InfoCard title="Company" icon={Building2}>
          <InfoRow icon={Globe} label="Website">
            {company.website ? (
              <a href={safeHref(company.website)} target="_blank" rel="noopener noreferrer" className={link}>
                <span className="truncate">{company.domain ?? company.website}</span> <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
              </a>
            ) : (
              "—"
            )}
          </InfoRow>
          <InfoRow icon={MapPin} label="Location">
            {location(company.city, company.country)}
          </InfoRow>
          <InfoRow icon={Briefcase} label="Industry">
            {company.industry ??
              (discovered?.category ? discovered.category.replace(/_/g, " ").replace(/^\w/, (ch) => ch.toUpperCase()) : "—")}
          </InfoRow>
          {company.company_size && (
            <InfoRow icon={Users} label="Company size">
              {company.company_size} employees
            </InfoRow>
          )}
          {company.address && (
            <InfoRow icon={MapPin} label="Address">
              {company.address}
            </InfoRow>
          )}
        </InfoCard>

        <InfoCard title="TECOMSA" icon={ShieldCheck}>
          <InfoRow icon={ShieldCheck} label="Relationship">
            <CrmStatusBadge status={company.odoo_status} />
          </InfoRow>
          <InfoRow icon={UserCheck} label="Odoo owner">
            {company.salesperson?.name ?? "—"}
          </InfoRow>
          <InfoRow icon={Database} label="Source">
            {company.sources.length > 1 ? Array.from(new Set(company.sources.map((s) => s.source_label))).join(", ") : company.source_label}
          </InfoRow>
          <InfoRow icon={CalendarDays} label="Added">
            {formatDate(company.created_at)} · {company.creator?.name ?? "unknown"}
          </InfoRow>
          {discovered && (
            <InfoRow icon={Radar} label="Discovered">
              {formatDate(discovered.first_seen_at)}
              {discovered.first_seen_run_id && (
                <Link href={`/discovery/${discovered.first_seen_run_id}`} className="text-accent hover:underline">
                  · search #{discovered.first_seen_run_id}
                </Link>
              )}
            </InfoRow>
          )}
        </InfoCard>
      </div>

      {ev && (
        <InfoCard title="Why discovery picked it" icon={Sparkles}>
          <div className="flex flex-wrap items-center gap-2">
            <ConfidenceBadge value={ev.confidence} />
            <span className="text-xs text-fg-subtle">
              How well public sources support this being a real company in this industry (
              <Link href={`/discovery/${ev.run_id}`} className="text-accent hover:underline">
                search #{ev.run_id}
              </Link>
              ). Not its size, fit or sales readiness.
            </span>
          </div>
          <ul className="stagger mt-3 grid gap-2 text-[13px] sm:grid-cols-2">
            {ev.reasons.map((r) => (
              <li key={r} className="flex gap-2 rounded-md border border-success/20 bg-success-soft/50 px-3 py-2">
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" strokeWidth={3} aria-label="Supports" />
                {r}
              </li>
            ))}
            {ev.concerns.map((c) => (
              <li key={c} className="flex gap-2 rounded-md border border-border bg-surface-muted/60 px-3 py-2 text-fg-muted">
                <Minus className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fg-subtle" aria-label="Against" />
                {c}
              </li>
            ))}
          </ul>
          {ev.signals.length > 0 && <p className="mt-3 text-xs text-fg-muted">Business-scale signals: {ev.signals.join(" · ")}</p>}
        </InfoCard>
      )}

      {company.description && (
        <InfoCard title="Description" icon={StickyNote}>
          <p className="whitespace-pre-line text-[13px] leading-6 text-fg">{company.description}</p>
        </InfoCard>
      )}

      {dupes.length === 0 ? (
        <div className="flex items-center gap-3 rounded-lg border border-success/20 bg-success-soft/40 px-4 py-3 text-[13px]">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-success text-white" aria-hidden>
            <Check className="h-3.5 w-3.5" strokeWidth={3} />
          </span>
          <p>
            <span className="font-medium text-fg">No likely duplicates.</span>{" "}
            <span className="text-fg-muted">Checked by domain, email domain, phone and name.</span>
          </p>
        </div>
      ) : (
        <InfoCard title={`Possible duplicates (${dupes.length})`} icon={Copy}>
          <ul className="stagger divide-y divide-border">
            {dupes.map((d) => (
              <li key={d.company.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-[13px]">
                <Avatar name={d.company.name} size="sm" />
                <RowLink href={`/companies/${d.company.id}`}>{d.company.name}</RowLink>
                <CrmStatusBadge status={d.company.odoo_status} />
                <span className="text-xs text-fg-muted">{d.reason}</span>
              </li>
            ))}
          </ul>
        </InfoCard>
      )}
    </div>
  );
}

/** OpenStreetMap embed centred on one point (no API key, no tracking script). */
function osmEmbed(lat: number, lon: number) {
  const d = 0.006;
  const bbox = [lon - d, lat - d * 0.6, lon + d, lat + d * 0.6].map((n) => n.toFixed(5)).join(",");
  return `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat.toFixed(6)},${lon.toFixed(6)}`;
}

/** Every physical location (branch, factory, shop): cards on the left, a live map of the selected one. */
function LocationsTab({ company }: { company: CompanyDetail }) {
  const locations = company.locations;
  const [selected, setSelected] = useState(() => Math.max(0, locations.findIndex((l) => l.latitude !== null && l.longitude !== null)));
  const current = locations[selected];
  const cities = Array.from(new Set(locations.map((l) => l.city).filter(Boolean))) as string[];
  if (!locations.length) {
    return (
      <Section>
        <EmptyState icon={<MapPin />} title="No locations recorded" description="Locations come from discovery searches." />
      </Section>
    );
  }
  const hasPoint = current?.latitude != null && current?.longitude != null;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-[13px] text-fg-muted">
        <span>
          <span className="font-display text-[20px] font-semibold tabular text-fg">
            <CountUp value={locations.length} reveal="locations" />
          </span>{" "}
          location{locations.length === 1 ? "" : "s"}
          {cities.length > 0 && ` in ${cities.length} cit${cities.length === 1 ? "y" : "ies"}`}
        </span>
        <span className="stagger flex flex-wrap gap-1.5">
          {cities.map((c) => (
            <span key={c} className="rounded-full border border-border bg-surface px-2.5 py-0.5 text-xs">
              {c}
            </span>
          ))}
        </span>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <ul className="stagger space-y-2.5">
          {locations.map((l, i) => {
            const active = i === selected;
            const point = l.latitude != null && l.longitude != null;
            return (
              <li key={`${l.name}|${l.city}|${l.address}|${l.first_seen_at}`}>
                <button
                  type="button"
                  onClick={() => setSelected(i)}
                  aria-pressed={active}
                  className={clsx(
                    "group flex w-full gap-3 rounded-lg border bg-surface p-3.5 text-left shadow-xs transition-[border-color,box-shadow,transform] duration-200",
                    active ? "border-accent/50 shadow-[0_0_0_3px_rgb(var(--accent)/0.12)]" : "border-border hover:-translate-y-px hover:border-border-strong",
                  )}
                >
                  <MapPin className={clsx("mt-0.5 h-4 w-4 shrink-0 transition-colors duration-150", active ? "text-accent" : "text-fg-subtle")} aria-hidden />
                  <span className="min-w-0 flex-1 text-[13px]">
                    <span className="block truncate font-medium text-fg">{l.name ?? company.name}</span>
                    <span className="block truncate text-fg-muted">{[l.address, l.city].filter(Boolean).join(" · ") || "Address unknown"}</span>
                    <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-fg-subtle">
                      {l.phone && <span className="tabular">{l.phone}</span>}
                      {l.sources.map((s) => (
                        <span key={s} className="rounded-sm bg-surface-muted px-1.5 py-px ring-1 ring-inset ring-border">
                          {s}
                        </span>
                      ))}
                      <span>Found {formatDate(l.first_seen_at)}</span>
                      {!point && <span>· not on the map</span>}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        <div className="lg:sticky lg:top-4 lg:self-start">
          <div className="overflow-hidden rounded-lg border border-border bg-surface shadow-card">
            {hasPoint ? (
              <iframe
                key={selected}
                title={`Map of ${current?.name ?? company.name}`}
                src={osmEmbed(current!.latitude!, current!.longitude!)}
                className="h-[360px] w-full animate-[fade-in_400ms_ease-out] border-0"
                loading="lazy"
                referrerPolicy="no-referrer"
              />
            ) : (
              <div className="flex h-[360px] items-center justify-center">
                <EmptyState compact icon={<MapPin />} title="No map position" description="This location has no coordinates in the source data." />
              </div>
            )}
            {hasPoint && (
              <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-2.5 text-xs">
                <span className="mr-auto truncate font-medium text-fg">{current?.name ?? company.name}</span>
                <a
                  href={`https://www.google.com/maps/dir/?api=1&destination=${current!.latitude},${current!.longitude}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 rounded-full bg-accent px-3 py-1 font-medium text-white transition-colors hover:bg-accent-hover"
                >
                  <Navigation className="h-3 w-3" aria-hidden /> Directions
                </a>
                <a
                  href={`https://www.openstreetmap.org/?mlat=${current!.latitude}&mlon=${current!.longitude}#map=17/${current!.latitude}/${current!.longitude}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 rounded-full border border-border px-3 py-1 font-medium text-fg-muted transition-colors hover:text-fg"
                >
                  Larger map <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              </div>
            )}
          </div>
          <p className="mt-1.5 text-[11px] text-fg-subtle">Map © OpenStreetMap contributors.</p>
        </div>
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
          empty={<EmptyState compact icon={<Handshake />} title="No CRM records match this company" description="Nothing in TECOMSA's imported Odoo CRM matches its name, domain, email domain or phone." />}
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
            { key: "stage", header: "Stage", cell: (r) => (r.stage ? <span className="rounded-full border border-border bg-surface-muted/60 px-2 py-0.5 text-xs font-medium">{r.stage}</span> : <span className="text-fg-subtle">—</span>) },
            {
              key: "state",
              header: "State",
              cell: (r) =>
                <CrmStateBadge lead={r} />,
            },
            { key: "owner", header: "Salesperson", cell: (r) => (r.salesperson_name ? <span className="inline-flex items-center gap-2 text-fg-muted"><Avatar name={r.salesperson_name} size="sm" />{r.salesperson_name}</span> : <span className="text-fg-subtle">—</span>) },
            { key: "rev", header: "Expected revenue", align: "right", cell: (r) => <span className={r.expected_revenue ? "font-semibold text-fg" : "text-fg-subtle"}>{formatMoney(r.expected_revenue)}</span> },
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
          empty={<EmptyState compact icon={<Contact />} title="No Odoo contacts match this company" description="No imported Odoo contact is linked to it yet." />}
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
            { key: "phone", header: "Phone", cell: (r) => <ContactValue kind="phone" value={r.mobile ?? r.phone} /> },
            { key: "email", header: "Email", cell: (r) => <ContactValue kind="email" value={r.email} /> },
            { key: "loc", header: "Location", cell: (r) => <span className="text-fg-muted">{location(r.city, r.country)}</span> },
          ]}
        />
      </Section>
    </div>
  );
}

const CONTACT_SOURCE_LABEL: Record<string, string> = { MANUAL: "Manual", ODOO_IMPORT: "Odoo contact import" };

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
      toast.success("Contact added");
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
        <Button type="submit" loading={saving}>
          <Save className="h-3.5 w-3.5" aria-hidden /> Save contact
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
                  <a href={safeHref(c.linkedin_url)} target="_blank" rel="noopener noreferrer" className="ml-2 text-xs font-normal text-accent hover:underline">
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
            <Plus className="h-3.5 w-3.5" aria-hidden /> Add
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
      toast.success("Note added");
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
          <Button type="submit" variant="secondary" size="sm" loading={saving} disabled={!notes.trim()}>
            <StickyNote className="h-3.5 w-3.5" aria-hidden /> Add note
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

// ---- Candidate ownership ---------------------------------------------------------

function CandidateOwnership({ company, onChanged }: { company: CompanyDetail; onChanged: () => void }) {
  const me = useCurrentUser();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (company.source !== "DISCOVERY" || !me) return null;
  const mine = company.owner?.id === me.id;
  const action = company.owner === null ? (company.is_protected ? null : "claim") : mine || isPrivileged(me) ? "release" : null;
  if (!action) return null;
  async function run() {
    setBusy(true);
    setError(null);
    try {
      await api(`/companies/${company.id}/${action}`, { method: "POST" });
      if (action === "claim") toast.success("Claimed", `${company.name} is now marked as yours.`);
      else toast.info("Claim released", "Other salespeople can now claim this company.");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the candidate.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <span className="inline-flex items-center gap-2">
      {error && <span className="text-[13px] text-danger">{error}</span>}
      <Button
        variant="secondary"
        disabled={busy}
        onClick={run}
        title={action === "claim" ? "Mark this company as yours so teammates know you are working it" : "Let other salespeople claim this company"}
      >
        {action === "claim" ? "Claim for me" : "Release claim"}
      </Button>
    </span>
  );
}

// ---- Page ------------------------------------------------------------------------

function CompanyProfile() {
  const { id } = useParams<{ id: string }>();
  const { data: company, error, loading, reload } = useApi<CompanyDetail>(`/companies/${id}`);
  const [state, setState] = useUrlState(["tab"] as const);
  const tab = (state.tab || "overview") as TabKey;
  // Feed the command menu's "Recently viewed" list.
  useEffect(() => {
    if (company) rememberCompany(company);
  }, [company]);
  const [researchOpen, setResearchOpen] = useState(false);
  const [researchKey, setResearchKey] = useState(0);
  const [opportunityOpen, setOpportunityOpen] = useState(false);
  const [opportunityKey, setOpportunityKey] = useState(0);
  const sales = useOpportunity(Number(id), opportunityKey);

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
  const opportunity = sales.data?.opportunity;
  // The primary action once a lead is worth working: create its Odoo opportunity (one per company).
  const canCreateOpportunity =
    sales.data !== null && (opportunity ? !opportunity.limited && opportunity.sync_status !== "SYNCED" && opportunity.sync_status !== "SYNCING" : !company.is_protected);
  const salesChanged = () => {
    setOpportunityKey((k) => k + 1);
    void reload();
  };
  const heroPhone = company.main_phone ?? company.contacts[0]?.business_phone ?? null;
  const heroEmail = company.main_email ?? company.contacts[0]?.business_email ?? null;
  const quickAction =
    "group inline-flex max-w-full items-center gap-1.5 truncate rounded-full border border-white/25 bg-white/10 px-3 py-1.5 text-[12.5px] font-medium text-white backdrop-blur-sm transition-[background-color,transform] hover:-translate-y-px hover:bg-white/20";
  return (
    <>
      <header
        className="relative mb-5 animate-page-in overflow-hidden rounded-xl text-white shadow-card"
        style={{
          background:
            "radial-gradient(90% 140% at 100% 0%, rgb(214 28 36) 0%, transparent 60%), linear-gradient(135deg, rgb(150 6 12) 0%, rgb(196 18 26) 55%, rgb(120 4 8) 100%)",
        }}
      >
        <div className="relative px-6 pb-5 pt-5 md:px-8">
          <nav aria-label="Breadcrumb">
            <ol className="flex items-center gap-1 text-xs text-white/70">
              <li>
                <Link href="/companies" className="transition-colors hover:text-white">
                  Companies
                </Link>
              </li>
              <li className="flex min-w-0 items-center gap-1">
                <ChevronRight className="h-3 w-3 shrink-0" aria-hidden />
                <span aria-current="page" className="truncate">{company.name}</span>
              </li>
            </ol>
          </nav>
          <div className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] items-start gap-4 xl:flex xl:flex-wrap">
            <span className="animate-pop-in rounded-2xl bg-white p-1.5 shadow-[0_8px_24px_-8px_rgb(0_0_0/0.45)]">
              <Avatar name={company.name} size="xl" domain={company.domain} />
            </span>
            <div className="min-w-0 flex-1">
              <h1 className="break-words text-[22px] font-semibold leading-7 tracking-[-0.02em] text-white sm:text-[28px] sm:leading-9">{company.name}</h1>
              <div className="stagger mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                <CrmStatusBadge status={company.odoo_status} />
                {company.industry && <span className="whitespace-nowrap rounded-full border border-white/20 bg-white/10 px-2.5 py-0.5">{company.industry}</span>}
                <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-white/20 bg-white/10 px-2.5 py-0.5">
                  <MapPin className="h-3 w-3" aria-hidden /> {location(company.city, company.country)}
                </span>
                <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-white/20 bg-white/10 px-2.5 py-0.5">
                  <UserCheck className="h-3 w-3" aria-hidden /> Odoo owner: {company.salesperson?.name ?? "—"}
                </span>
                {company.owner && (
                  <span className="whitespace-nowrap rounded-full border border-white/20 bg-white/10 px-2.5 py-0.5">Found by {company.owner.name}</span>
                )}
              </div>
            </div>
            <div className="col-span-2 flex flex-wrap items-center gap-2 xl:col-span-1 [&_button]:border-white/30 [&_button]:bg-white/10 [&_button]:text-white [&_button:hover]:bg-white/20">
              <CandidateOwnership company={company} onChanged={reload} />
              {!company.is_protected && (
                <Button variant="secondary" onClick={() => setResearchOpen(true)}>
                  <Search className="h-3.5 w-3.5" aria-hidden /> Research company
                </Button>
              )}
              {canCreateOpportunity && (
                <button
                  type="button"
                  onClick={() => setOpportunityOpen(true)}
                  className="inline-flex h-9 items-center gap-1.5 rounded bg-white px-3.5 text-[13.5px] font-semibold text-accent shadow-xs transition-[transform,box-shadow] hover:-translate-y-px hover:shadow-card-hover"
                >
                  <Briefcase className="h-3.5 w-3.5" aria-hidden /> Create opportunity
                </button>
              )}
              {company.can_edit && (
                <Link
                  href={`/companies/${company.id}/edit`}
                  className="inline-flex h-9 items-center gap-1.5 rounded bg-white px-3.5 text-[13.5px] font-semibold text-accent shadow-xs transition-[transform,box-shadow] hover:-translate-y-px hover:shadow-card-hover"
                >
                  <Pencil className="h-3.5 w-3.5" aria-hidden /> Edit
                </Link>
              )}
            </div>
          </div>
          {(heroPhone || heroEmail || company.website) && (
            <div className="stagger mt-4 flex flex-wrap gap-2">
              {heroPhone && (
                <a href={`tel:${heroPhone.replace(/[^\d+]/g, "")}`} className={quickAction}>
                  <Phone className="h-3.5 w-3.5" aria-hidden /> <span className="tabular">{heroPhone}</span>
                </a>
              )}
              {heroEmail && (
                <a href={`mailto:${heroEmail}`} className={quickAction}>
                  <Mail className="h-3.5 w-3.5" aria-hidden /> {heroEmail}
                </a>
              )}
              {company.website && (
                <a href={safeHref(company.website)} target="_blank" rel="noopener noreferrer" className={quickAction}>
                  <Globe className="h-3.5 w-3.5" aria-hidden /> {company.domain ?? "Website"} <ExternalLink className="h-3 w-3 opacity-70" aria-hidden />
                </a>
              )}
            </div>
          )}
        </div>
        <ProtectionStrip company={company} />
      </header>
      <OpportunityCard companyId={company.id} opportunity={opportunity} onCreate={() => setOpportunityOpen(true)} onChanged={salesChanged} />
      <ResearchSummary companyId={company.id} refreshKey={researchKey} onCreateOpportunity={canCreateOpportunity ? () => setOpportunityOpen(true) : undefined} />
      <OpportunityModal
        open={opportunityOpen}
        companyId={company.id}
        companyName={company.name}
        onClose={() => setOpportunityOpen(false)}
        onDone={() => {
          setOpportunityOpen(false);
          salesChanged();
        }}
      />
      <ResearchModal
        open={researchOpen}
        companyId={company.id}
        onClose={() => setResearchOpen(false)}
        onStarted={() => {
          setResearchOpen(false);
          setResearchKey((k) => k + 1);
        }}
      />
      <div className="mb-4">
        <Tabs<TabKey>
          label="Company sections"
          value={tab}
          onChange={(key) => setState({ tab: key === "overview" ? "" : key })}
          tabs={[
            { key: "overview", label: "Overview", icon: LayoutGrid },
            ...(company.locations.length ? [{ key: "locations" as const, label: "Locations", count: company.locations.length, icon: MapPin }] : []),
            { key: "relationship", label: "TECOMSA relationship", count: rel.crm_records.length + rel.odoo_contacts.length, icon: Handshake },
            { key: "intelligence", label: "Intelligence", icon: Sparkles },
            { key: "people", label: "Decision makers", icon: UserCheck },
            { key: "contacts", label: "LeadFinder contacts", count: company.contacts.length, icon: Users },
            { key: "campaigns", label: "Campaigns", count: company.campaigns.length, icon: Megaphone },
            { key: "activity", label: "Activity", icon: ActivityIcon },
          ]}
        />
      </div>
      <div key={tab} role="tabpanel" tabIndex={0} className="animate-page-in focus-visible:outline-offset-4">
        {tab === "overview" && <OverviewTab company={company} />}
        {tab === "locations" && <LocationsTab company={company} />}
        {tab === "relationship" && <RelationshipTab company={company} />}
        {tab === "intelligence" && <CompanyIntelligence company={company} onResearch={() => setResearchOpen(true)} refreshKey={researchKey} />}
        {tab === "people" && <CompanyDecisionMakers company={company} />}
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
