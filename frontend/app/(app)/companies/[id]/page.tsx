"use client";

import { Building2, ExternalLink, FileText, Lightbulb, Mail, Phone, RefreshCw, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Avatar,
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  DescriptionList,
  EmptyState,
  ErrorState,
  PageHeader,
  Section,
  Select,
  Skeleton,
  Tabs,
  toast,
  type Tone,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { COMPANY_STATUS, COMPANY_STATUSES, humanize, place } from "@/lib/companies";
import { formatDate, formatDateTime } from "@/lib/format";
import { safeHref } from "@/lib/url";
import { isActive, pollDelay, researchView, POLL_LIMIT_MS } from "@/lib/people-research";
import type { CompanyDetail, CompanyPerson, CompanySignal, CompanyStatus, SignalGroup } from "@/types/v2";

type TabKey = "overview" | "people" | "opportunity" | "sources";

const muted = (text: string) => <span className="text-fg-subtle">{text}</span>;

function ExternalLinkText({ href, label }: { href: string | null; label: string | null }) {
  const safe = safeHref(href);
  if (!safe) return muted("—");
  return (
    <a href={safe} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
      {label ?? safe}
      <ExternalLink className="h-3 w-3" aria-hidden />
    </a>
  );
}

const SIGNAL_GROUPS: { key: SignalGroup; label: string }[] = [
  { key: "activity", label: "Business activities" },
  { key: "operations", label: "Operations" },
  { key: "technology", label: "Technology" },
  { key: "hiring", label: "Hiring" },
  { key: "news", label: "Company news" },
];

function signalLabel(s: CompanySignal): string {
  if (s.signal_type === "technology" || s.group === "news") return s.signal_value ?? humanize(s.signal_type);
  if (s.signal_type === "hiring_department") return `Hiring: ${humanize(s.signal_value)}`;
  return s.signal_value ? `${humanize(s.signal_type)}: ${s.signal_value}` : humanize(s.signal_type);
}

function employees(c: CompanyDetail["company"]) {
  if (c.employee_count_estimate) return c.employee_count_estimate.toLocaleString();
  if (c.employee_count_min && c.employee_count_max) return `${c.employee_count_min.toLocaleString()}–${c.employee_count_max.toLocaleString()}`;
  if (c.employee_count_min) return `${c.employee_count_min.toLocaleString()}+`;
  return muted("—");
}

/** Research status of the company (website enrichment); nothing while it was never researched. */
function ResearchState({ c }: { c: CompanyDetail["company"] }) {
  if (c.enrichment_status === "queued" || c.enrichment_status === "researching")
    return (
      <Badge tone="info" dot live>
        Researching company…
      </Badge>
    );
  if (c.enrichment_status === "partial") return <Badge tone="warning">Research partial</Badge>;
  if (c.enrichment_status === "failed") return <Badge tone="danger">Research failed</Badge>;
  if (c.last_enriched_at) return <span className="text-xs text-fg-subtle">Researched {formatDate(c.last_enriched_at)}</span>;
  return null;
}

function Overview({ detail }: { detail: CompanyDetail }) {
  const c = detail.company;
  const socials = (
    [
      ["Facebook", c.facebook_url],
      ["Instagram", c.instagram_url],
      ["LinkedIn", c.linkedin_url],
      ["YouTube", c.youtube_url],
      ["TikTok", c.tiktok_url],
      ["X", c.twitter_url],
    ] as const
  ).filter(([, url]) => url);
  // A signal with a value ("Factory: 3") makes the same signal without one redundant.
  const valued = new Set(detail.signals.filter((s) => s.signal_value && s.group !== "technology" && s.group !== "news" && s.group !== "hiring").map((s) => s.signal_type));
  const signals = detail.signals.filter((s) => s.group !== "events" && (s.signal_value || !valued.has(s.signal_type)));
  const timeline = detail.signals
    .filter((s) => s.group === "events" && s.event_date)
    .sort((a, b) => (b.event_date ?? "").localeCompare(a.event_date ?? ""));
  const relationships = detail.relationships ?? [];
  const products = detail.offerings.filter((o) => o.kind !== "service");
  const services = detail.offerings.filter((o) => o.kind === "service");
  const contacts = [
    ...detail.phones.map((p) => ({ id: `p${p.id}`, value: p.phone, kind: p.phone_type === "whatsapp" ? "WhatsApp" : "Phone", purpose: p.purpose, confidence: p.confidence })),
    ...detail.emails.map((e) => ({ id: `e${e.id}`, value: e.email, kind: "Email", purpose: e.purpose, confidence: e.confidence })),
  ];
  return (
    <div className="space-y-5">
      <Section title="Company" actions={<ResearchState c={c} />}>
        {c.enrichment_status === "partial" && c.enrichment_message && <p className="mb-4 text-xs text-fg-muted">{c.enrichment_message}</p>}
        {detail.overview && <p className="mb-4 text-[13px] text-fg">{detail.overview}</p>}
        <DescriptionList
          inline
          items={[
            { label: "Legal name", value: c.legal_name ?? muted("—") },
            { label: "Website", value: <ExternalLinkText href={c.website} label={c.domain ?? c.website} /> },
            { label: "Industry", value: [c.industry, c.sub_industry].filter(Boolean).join(" · ") || muted("—") },
            { label: "Type", value: c.company_type ?? muted("—") },
            { label: "Employees", value: employees(c) },
            { label: "Founded", value: c.founded_year ?? muted("—") },
            { label: "Headquarters", value: place(c.headquarters_city, c.headquarters_region, c.headquarters_country) },
            ...(relationships.length
              ? [
                  {
                    label: "Group",
                    value: relationships.map((r) => `${humanize(r.relation_type)}: ${r.related_name}`).join(" · "),
                  },
                ]
              : []),
            { label: "Phone", value: c.primary_phone ?? muted("—") },
            { label: "Email", value: c.primary_email ?? muted("—") },
            {
              label: "Social profiles",
              value: socials.length ? (
                <span className="flex flex-wrap gap-x-3 gap-y-1">
                  {socials.map(([label, url]) => (
                    <ExternalLinkText key={label} href={url} label={label} />
                  ))}
                </span>
              ) : (
                muted("—")
              ),
            },
            { label: "Last verified", value: c.last_verified_at ? formatDate(c.last_verified_at) : muted("Never") },
            { label: "Added", value: formatDate(c.created_at) },
          ]}
        />
        {c.description && <p className="mt-4 whitespace-pre-line text-[13px] text-fg-muted">{c.description}</p>}
      </Section>
      {signals.length > 0 && (
        <Section title="Operations">
          <div className="space-y-3">
            {SIGNAL_GROUPS.map(({ key, label }) => {
              const rows = signals.filter((s) => s.group === key);
              if (!rows.length) return null;
              return (
                <div key={key}>
                  <p className="mb-1.5 text-xs font-medium text-fg-muted">{label}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {rows.map((s) => (
                      <span key={s.id} title={`Confidence ${s.confidence ?? "—"}`}>
                        <Badge tone={key === "news" ? "info" : "neutral"}>{signalLabel(s)}</Badge>
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </Section>
      )}
      {timeline.length > 0 && (
        <Section title="Timeline" description="Dated business events, each from a public source.">
          <ul className="space-y-2">
            {timeline.map((e) => (
              <li key={e.id} className="flex gap-3 text-[13px]">
                <span className="w-24 shrink-0 tabular-nums text-fg-muted">{e.event_date ? formatDate(e.event_date) : "—"}</span>
                <span className="min-w-0">
                  <Badge tone="info">{humanize(e.signal_type)}</Badge> <span className="text-fg">{e.description}</span>
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {detail.offerings.length > 0 && (
        <Section title="Products & services">
          <div className="space-y-3">
            {[
              { label: "Products", rows: products },
              { label: "Services", rows: services },
            ].map(({ label, rows }) =>
              rows.length ? (
                <div key={label}>
                  <p className="mb-1.5 text-xs font-medium text-fg-muted">{label}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {rows.map((o) => (
                      <Badge key={o.id}>{o.raw_name}</Badge>
                    ))}
                  </div>
                </div>
              ) : null,
            )}
          </div>
        </Section>
      )}
      {contacts.length > 0 && (
        <Section title="Contact" flush>
          <DataTable
            caption="Company contact details"
            rows={contacts}
            rowKey={(r) => r.id}
            columns={[
              { key: "value", header: "Contact", cell: (r) => <span className="font-medium tabular">{r.value}</span> },
              { key: "kind", header: "Type", cell: (r) => r.kind },
              { key: "purpose", header: "For", cell: (r) => humanize(r.purpose) },
              { key: "confidence", header: "Confidence", align: "right", cell: (r) => r.confidence ?? "—" },
            ]}
          />
        </Section>
      )}
      <Section title="Locations" flush>
        <DataTable
          caption="Locations"
          rows={detail.locations}
          rowKey={(l) => l.id}
          empty={<EmptyState compact title="No locations recorded" />}
          columns={[
            {
              key: "place",
              header: "Location",
              cell: (l) => (
                <span>
                  {l.name && <span className="block font-medium">{l.name}</span>}
                  {place(l.city, l.region, l.country)}
                </span>
              ),
            },
            { key: "type", header: "Type", cell: (l) => humanize(l.location_type) },
            { key: "address", header: "Address", cell: (l) => l.address ?? muted("—") },
            { key: "phone", header: "Phone", cell: (l) => l.phone ?? muted("—") },
            { key: "hq", header: "", cell: (l) => (l.is_headquarters ? <Badge tone="accent">Headquarters</Badge> : null) },
          ]}
        />
      </Section>
    </div>
  );
}

const KEY_DEPARTMENTS: { key: string; label: string; always?: boolean }[] = [
  { key: "executive", label: "Executive", always: true },
  { key: "it", label: "IT", always: true },
  { key: "marketing", label: "Marketing", always: true },
  { key: "finance", label: "Finance", always: true },
  { key: "sales", label: "Sales", always: true },
  { key: "hr", label: "HR", always: true },
  { key: "operations", label: "Operations", always: true },
  { key: "procurement", label: "Procurement", always: true },
  { key: "supply_chain", label: "Supply chain" },
  { key: "customer_experience", label: "Customer experience" },
  { key: "e_commerce", label: "E-commerce & digital" },
  { key: "manufacturing", label: "Manufacturing" },
  { key: "legal", label: "Legal" },
  { key: "administration", label: "Administration" },
];
const DEPARTMENT_LABEL = Object.fromEntries(KEY_DEPARTMENTS.map((d) => [d.key, d.label]));
const SOURCE_LABEL: Record<string, string> = {
  company_website: "Company website",
  conference: "Conference",
  event: "Event",
  association: "Association",
  news: "News",
  case_study: "Case study",
  public_pdf: "Public document",
  government: "Official record",
  public_directory: "Directory",
  public_web: "Public web",
  web_archive: "Archived website",
  open_dataset: "Wikidata",
};

/** Where a person's role is stated: "Company website", "Conference"... (each once). */
function sourceLabels(p: CompanyPerson): string[] {
  return [...new Set(p.sources.map((s) => SOURCE_LABEL[s.source_type ?? ""] ?? "Public source"))];
}
const EMPLOYMENT: Record<CompanyPerson["employment_status"], { label: string; tone: Tone }> = {
  current: { label: "Current", tone: "success" },
  unknown: { label: "Not confirmed", tone: "neutral" },
  former: { label: "Former", tone: "neutral" },
};

function confidence(value: number | null) {
  if (value === null) return muted("—");
  const [label, tone]: [string, Tone] = value >= 75 ? ["High", "success"] : value >= 50 ? ["Medium", "info"] : ["Low", "warning"];
  return (
    <span title={`Confidence ${value}`}>
      <Badge tone={tone}>{label}</Badge>
    </span>
  );
}

/** People of the company's parent / group: shown for context, never as employees of this company. */
function GroupContacts({ detail }: { detail: CompanyDetail }) {
  const rows = detail.related_group_people ?? [];
  if (!rows.length) return null;
  return (
    <div className="mt-4 border-t border-border pt-3">
      <p className="mb-2 text-xs font-medium text-fg-muted">Group-level contacts</p>
      <ul className="space-y-1.5 text-[13px]">
        {rows.map((p) => (
          <li key={`${p.employer_id}-${p.person_id}-${p.job_title}`}>
            <Link href={`/companies/${p.employer_id}`} className="text-fg hover:underline">
              {p.full_name}
            </Link>{" "}
            <span className="text-fg-muted">
              · {p.job_title} · {p.employer_name} ({humanize(p.relation_type)})
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const CONTACT_TONE: Record<string, Tone> = {
  confirmed_email: "success",
  verified_email: "success",
  published_email: "info",
  business_mobile: "info",
  direct_business_phone: "info",
  whatsapp: "info",
  office_extension: "info",
  business_phone: "warning",
  high_confidence_email: "warning",
  catch_all_email: "warning",
  predicted_email: "warning",
};

/** A person's strongest contact method with its honest label, the others on hover; else the company fallback. */
function BestContact({ person, switchboard, generalEmail }: { person: CompanyPerson; switchboard: string | null; generalEmail: string | null }) {
  const [best, ...others] = person.contacts ?? [];
  return (
    <div className="space-y-0.5 text-xs">
      {best ? (
        <span className="flex flex-wrap items-center gap-1.5" title={others.map((o) => `${o.value} · ${o.label}`).join("\n")}>
          {best.kind.endsWith("email") ? <Mail className="h-3.5 w-3.5 text-fg-subtle" aria-hidden /> : <Phone className="h-3.5 w-3.5 text-fg-subtle" aria-hidden />}
          <span className="tabular text-fg">{best.value}</span>
          <Badge tone={CONTACT_TONE[best.kind] ?? "neutral"}>{best.label}</Badge>
          {others.length > 0 && <span className="text-fg-subtle">+{others.length}</span>}
        </span>
      ) : null}
      {!person.contactable && (switchboard || generalEmail) && (
        <span className="block text-fg-subtle">
          {best ? "Or the company: " : "No verified contact yet · company: "}
          {[switchboard, generalEmail].filter(Boolean).join(" · ")}
        </span>
      )}
      {!best && !switchboard && !generalEmail && <span className="text-fg-subtle">No verified contact yet</span>}
    </div>
  );
}

// What real sales activity showed: applied to the contact graph at once (POST /companies/{id}/contact-feedback).
const FEEDBACK: { event: string; label: string; on: "email" | "phone" | "role" }[] = [
  { event: "delivered", label: "Email delivered", on: "email" },
  { event: "replied", label: "Email replied", on: "email" },
  { event: "hard_bounce", label: "Email bounced", on: "email" },
  { event: "number_confirmed", label: "Phone correct", on: "phone" },
  { event: "wrong_number", label: "Phone wrong", on: "phone" },
  { event: "company_switchboard", label: "Phone is the company line", on: "phone" },
  { event: "correct_person", label: "Correct person", on: "role" },
  { event: "person_left_company", label: "Left the company", on: "role" },
  { event: "wrong_person", label: "Wrong person", on: "role" },
];

function Feedback({ companyId, person, onChanged }: { companyId: number; person: CompanyPerson; onChanged: () => void }) {
  const email = person.emails.find((e) => e.status !== "invalid");
  const phone = person.phones.find((p) => p.status !== "invalid" && p.phone_type !== "company_switchboard");
  const options = FEEDBACK.filter((f) => (f.on === "email" ? email : f.on === "phone" ? phone : true));
  const send = async (event: string) => {
    const f = FEEDBACK.find((x) => x.event === event);
    if (!f) return;
    try {
      await api(`/companies/${companyId}/contact-feedback`, {
        method: "POST",
        body: { event, email_id: f.on === "email" ? email?.id : undefined, phone_id: f.on === "phone" ? phone?.id : undefined, company_person_id: f.on === "role" ? person.id : undefined },
      });
      toast.success(`${person.person.full_name}: ${f.label.toLowerCase()}`);
      onChanged();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save the feedback");
    }
  };
  return (
    <select aria-label={`Feedback on ${person.person.full_name}`} className="rounded border border-border bg-surface px-1 py-0.5 text-xs text-fg-muted" value="" onChange={(e) => void send(e.target.value)}>
      <option value="">Feedback…</option>
      {options.map((f) => (
        <option key={f.event} value={f.event}>
          {f.label}
        </option>
      ))}
    </select>
  );
}

function People({ detail, overdue, onChanged }: { detail: CompanyDetail; overdue: boolean; onChanged: () => void }) {
  const c = detail.company;
  const people = detail.people;
  const research = detail.people_research;
  const view = researchView(research, people.length > 0, overdue);
  const researched = !view.active && research?.state !== "idle";
  const finishedAt = research?.finished_at ?? c.people_researched_at;
  const state = view.badge ? (
    <Badge tone="info" dot live={!overdue}>
      {view.badge}
    </Badge>
  ) : finishedAt ? (
    <span className="text-xs text-fg-subtle">
      {view.note ? `${view.note} · ` : ""}Researched {formatDate(finishedAt)}
    </span>
  ) : null;
  if (!people.length) {
    return (
      <Section>
        <EmptyState
          icon={<Users />}
          title={view.emptyTitle}
          description={view.active ? "People appear here as they are found." : (view.note ?? research?.message ?? c.people_message ?? undefined)}
        />
        <GroupContacts detail={detail} />
      </Section>
    );
  }
  const keyPeople = new Map(people.filter((p) => p.is_key).map((p) => [p.department ?? "other", p]));
  const departments = KEY_DEPARTMENTS.filter((d) => d.always || keyPeople.has(d.key));
  // The company's own line / mailbox: a fallback to reach a named person, never presented as theirs.
  const switchboard = detail.phones[0]?.phone ?? c.primary_phone ?? null;
  const generalEmail = detail.emails[0]?.email ?? null;
  const contact = (p: CompanyPerson) => <BestContact person={p} switchboard={switchboard} generalEmail={generalEmail} />;
  return (
    <div className="space-y-5">
      <Section title="Key people" actions={state}>
        <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
          {departments.map((d) => {
            const p = keyPeople.get(d.key);
            return (
              <div key={d.key} className="min-w-0">
                <p className="mb-1 text-xs font-medium text-fg-muted">{d.label}</p>
                {p ? (
                  <div className="space-y-1">
                    <p className="truncate text-[13px] font-medium text-fg">{p.person.full_name}</p>
                    <p className="truncate text-xs text-fg-muted">{p.job_title}</p>
                    {contact(p)}
                    <span className="flex flex-wrap items-center gap-2">
                      {confidence(p.confidence)}
                      <span className="text-[11px] text-fg-subtle">{sourceLabels(p).join(" · ")}</span>
                    </span>
                  </div>
                ) : (
                  <p className="text-xs text-fg-subtle">{view.active ? "Researching…" : researched ? "None found in public sources" : "—"}</p>
                )}
              </div>
            );
          })}
        </div>
      </Section>
      <Section title="All people" description={`${people.length} found`} flush>
        <DataTable
          caption="All people"
          rows={people}
          rowKey={(p) => p.id}
          columns={[
            {
              key: "name",
              header: "Name",
              cell: (p) => (
                <span className="flex items-center gap-2">
                  <span className="font-medium">{p.person.full_name}</span>
                  {p.is_key && <Badge tone="accent">Key</Badge>}
                </span>
              ),
            },
            {
              key: "title",
              header: "Title",
              cell: (p) => (
                <span title={p.sources.map((s) => s.url ?? s.name).join("\n")}>
                  {p.job_title}
                  {p.normalized_title && p.normalized_title !== p.job_title && <span className="block text-xs text-fg-subtle">{p.normalized_title}</span>}
                </span>
              ),
            },
            { key: "department", header: "Department", cell: (p) => DEPARTMENT_LABEL[p.department ?? ""] ?? humanize(p.department) },
            { key: "seniority", header: "Seniority", cell: (p) => humanize(p.seniority) },
            { key: "status", header: "Status", cell: (p) => <Badge tone={EMPLOYMENT[p.employment_status].tone}>{EMPLOYMENT[p.employment_status].label}</Badge> },
            { key: "confidence", header: "Confidence", cell: (p) => confidence(p.confidence) },
            { key: "sources", header: "Sources", cell: (p) => <span className="text-xs text-fg-muted">{sourceLabels(p).join(" · ")}</span> },
            { key: "contact", header: "Contact", cell: (p) => contact(p) },
            { key: "verified", header: "Last verified", cell: (p) => (p.last_verified_at ? formatDate(p.last_verified_at) : muted("—")) },
            { key: "feedback", header: "", cell: (p) => <Feedback companyId={c.id} person={p} onChanged={onChanged} /> },
          ]}
        />
      </Section>
      {(detail.related_group_people ?? []).length > 0 && (
        <Section>
          <GroupContacts detail={detail} />
        </Section>
      )}
    </div>
  );
}

function Opportunity({ detail }: { detail: CompanyDetail }) {
  if (!detail.opportunities.length) {
    return (
      <Section>
        <EmptyState icon={<Lightbulb />} title="No opportunity analysis yet" description="Odoo, Frinzo and IT fit are analysed in a later release." />
      </Section>
    );
  }
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {detail.opportunities.map((o) => (
        <Section key={o.id} title={humanize(o.solution)} actions={o.fit_level && <Badge tone={o.fit_level === "high" ? "success" : "neutral"}>Fit: {humanize(o.fit_level)}</Badge>}>
          <p className="text-[13px] text-fg">{o.summary ?? muted("No summary")}</p>
          <p className="mt-3 text-xs text-fg-subtle">Generated {formatDateTime(o.generated_at)}</p>
        </Section>
      ))}
    </div>
  );
}

function Sources({ detail }: { detail: CompanyDetail }) {
  return (
    <div className="space-y-5">
      {detail.conflicts.length > 0 && (
        <Section title="Sources disagree" description="The value shown on the company is the one from the strongest source.">
          <ul className="space-y-1.5 text-[13px]">
            {detail.conflicts.map((c) => (
              <li key={c.field}>
                <span className="font-medium">{humanize(c.field)}:</span>{" "}
                {c.values.map((v, i) => (
                  <span key={v.value} className={i === 0 ? "text-fg" : "text-fg-muted"}>
                    {i > 0 && " · "}
                    {v.value} <span className="text-xs text-fg-subtle">({v.source ?? "source"})</span>
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </Section>
      )}
      <Section flush>
        <DataTable
          caption="Sources"
          rows={detail.sources}
          rowKey={(s) => s.id}
          empty={<EmptyState icon={<FileText />} title="No sources recorded" />}
          columns={[
            { key: "name", header: "Source", cell: (s) => <ExternalLinkText href={s.url} label={s.name ?? s.url} /> },
            { key: "type", header: "Type", cell: (s) => humanize(s.source_type) },
            {
              key: "facts",
              header: "Facts",
              cell: (s) =>
                s.facts.length ? (
                  <span className="text-xs text-fg-muted" title={s.facts.map(humanize).join(", ")}>
                    {s.facts.slice(0, 6).map(humanize).join(", ")}
                    {s.facts.length > 6 && ` +${s.facts.length - 6}`}
                  </span>
                ) : (
                  muted("—")
                ),
            },
            { key: "evidence", header: "Evidence", align: "right", cell: (s) => s.evidence_count },
            { key: "retrieved", header: "Retrieved", cell: (s) => formatDate(s.retrieved_at) },
          ]}
        />
      </Section>
    </div>
  );
}

export default function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const user = useCurrentUser();
  const { data, error, loading, reload } = useApi<CompanyDetail>(`/companies/${id}`);
  const [tab, setTab] = useState<TabKey>("overview");
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // One state drives polling: company research, or the people research state the API reports (never "no people").
  const researching =
    ["queued", "researching"].includes(data?.company.enrichment_status ?? "") ||
    ["queued", "researching"].includes(data?.company.contact_status ?? "") ||
    isActive(data?.people_research?.state);
  const [pollingSince, setPollingSince] = useState<number | null>(null);
  useEffect(() => setPollingSince((since) => (researching ? (since ?? Date.now()) : null)), [researching]);
  const overdue = pollingSince !== null && Date.now() - pollingSince > POLL_LIMIT_MS;

  // Research runs in the background: the page fills in as it progresses; polling stops on every final state and
  // slows down past the guardrail (the backend's own deadlines end every stage).
  useEffect(() => {
    const delay = pollDelay(researching && pollingSince !== null, Date.now() - (pollingSince ?? Date.now()));
    if (delay === null) return;
    const timer = setTimeout(() => void reload(), delay);
    return () => clearTimeout(timer);
  }, [researching, pollingSince, data, error, reload]);

  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (loading && !data) return <Skeleton className="h-64 w-full" />;
  if (!data) return null;
  const c = data.company;

  async function changeStatus(status: CompanyStatus) {
    setSaving(true);
    try {
      await api(`/companies/${id}/status`, { method: "PATCH", body: { status } });
      toast.success(`Status: ${COMPANY_STATUS[status].label}`);
      await reload();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not change the status");
    } finally {
      setSaving(false);
    }
  }

  async function refresh() {
    setSaving(true);
    try {
      await api(`/companies/${id}/refresh`, { method: "POST" });
      toast.success("Research started");
      await reload();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not start the research");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    setSaving(true);
    try {
      await api(`/companies/${id}`, { method: "DELETE" });
      toast.success(`${c.name} deleted`);
      router.push("/companies");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not delete the company");
      setSaving(false);
      setConfirmDelete(false);
    }
  }

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            <Avatar name={c.name} domain={c.domain} size="lg" />
            {c.name}
          </span>
        }
        breadcrumbs={[{ label: "Companies", href: "/companies" }, { label: c.name }]}
        meta={[c.industry, place(c.headquarters_city, c.headquarters_country), c.domain].filter((v) => v && v !== "—").join(" · ")}
        actions={
          <>
            {c.website && (
              <Button variant="secondary" onClick={refresh} disabled={saving || researching}>
                <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                Refresh research
              </Button>
            )}
            <Select aria-label="Status" value={c.status} disabled={saving} onChange={(e) => changeStatus(e.target.value as CompanyStatus)} className="w-48">
              {COMPANY_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {COMPANY_STATUS[s].label}
                </option>
              ))}
            </Select>
            {isPrivileged(user) && (
              <Button variant="danger" onClick={() => setConfirmDelete(true)} disabled={saving}>
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
                Delete
              </Button>
            )}
          </>
        }
      />
      <div className="mb-5">
        <Tabs
          label="Company sections"
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "overview", label: "Overview", icon: Building2 },
            { key: "people", label: "People", icon: Users, count: data.people.length },
            { key: "opportunity", label: "Opportunity", icon: Lightbulb },
            { key: "sources", label: "Sources", icon: FileText, count: data.sources.length },
          ]}
        />
      </div>
      <div role="tabpanel">
        {tab === "overview" && <Overview detail={data} />}
        {tab === "people" && <People detail={data} overdue={overdue} onChanged={reload} />}
        {tab === "opportunity" && <Opportunity detail={data} />}
        {tab === "sources" && <Sources detail={data} />}
      </div>
      <ConfirmDialog
        open={confirmDelete}
        title={`Delete ${c.name}?`}
        confirmLabel="Delete company"
        tone="danger"
        busy={saving}
        onConfirm={remove}
        onClose={() => setConfirmDelete(false)}
      >
        Removes the company, its locations, roles and search results; Find Leads will not add it again. People and
        source records are kept. To only hide it, set its status to Archived.
      </ConfirmDialog>
    </>
  );
}
