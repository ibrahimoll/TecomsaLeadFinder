"use client";

import { Building2, CalendarDays, ChevronRight, ExternalLink, FileText, Globe, Lightbulb, Mail, MapPin, MessageCircle, Phone, RefreshCw, Smartphone, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Avatar,
  Badge,
  Button,
  ConfirmDialog,
  CopyButton,
  DataTable,
  DescriptionList,
  EmptyState,
  ErrorState,
  PageHeader,
  Section,
  Field,
  Input,
  Select,
  Textarea,
  Skeleton,
  Tabs,
  toast,
  type Tone,
} from "@/components/ui";
import { AgentInsights } from "@/components/agent-insights";
import { LushaPeople } from "@/components/lusha-people";
import { api, ApiError, useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { COMPANY_STATUS, COMPANY_STATUSES, displayName, humanize, place } from "@/lib/companies";
import { formatDate, formatDateTime, formatPhone, isLebaneseMobile } from "@/lib/format";
import { safeHref } from "@/lib/url";
import { OwnerSelect, useUsers } from "@/components/owner-select";
import { isActive, pollDelay, researchView, POLL_LIMIT_MS } from "@/lib/people-research";
import type { CompanyDetail, CompanyPerson, CompanySignal, CompanyStatus, OpportunityFit, SignalGroup } from "@/types/v2";

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
    ...detail.phones.map((p) => ({ id: `p${p.id}`, value: p.phone, kind: p.phone_type === "whatsapp" ? "WhatsApp" : isLebaneseMobile(p.phone) ? "Mobile" : "Phone", purpose: p.purpose, confidence: p.confidence })),
    ...detail.emails.map((e) => ({ id: `e${e.id}`, value: e.email, kind: "Email", purpose: e.purpose, confidence: e.confidence })),
  ].sort((a, b) => CONTACT_ORDER.indexOf(a.kind) - CONTACT_ORDER.indexOf(b.kind)); // a mobile first: it often reaches a manager
  const facts = [
    { label: "Legal name", value: c.legal_name ?? muted("—") },
    { label: "Industry", value: [c.industry, c.sub_industry].filter(Boolean).join(" · ") || muted("—") },
    { label: "Type", value: c.company_type ?? muted("—") },
    { label: "Employees", value: employees(c) },
    { label: "Founded", value: c.founded_year ?? muted("—") },
    { label: "Headquarters", value: place(c.headquarters_city, c.headquarters_region, c.headquarters_country) },
    ...(relationships.length ? [{ label: "Group", value: relationships.map((r) => `${humanize(r.relation_type)}: ${r.related_name}`).join(" · ") }] : []),
    { label: "Data updated", value: c.last_verified_at ? formatDate(c.last_verified_at) : muted("Never") }, // when a source last stated it, not a human check
    { label: "Added", value: formatDate(c.created_at) },
  ];
  return (
    <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-5">
        <AgentInsights c={c} />
        <Section title="About" actions={<ResearchState c={c} />}>
          {c.enrichment_status === "partial" && c.enrichment_message && <p className="mb-3 text-xs text-fg-muted">{c.enrichment_message}</p>}
          {(detail.overview || c.description) && (
            <div className="mb-4 space-y-2 border-l-2 border-accent/60 pl-3">
              {detail.overview && <p className="text-[13.5px] leading-relaxed text-fg">{detail.overview}</p>}
              {c.description && <p className="whitespace-pre-line text-[13px] leading-relaxed text-fg-muted">{c.description}</p>}
            </div>
          )}
          <dl className="stagger grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {facts.map((f) => (
              <div key={f.label} className="min-w-0 rounded-lg bg-surface-muted/50 px-3 py-2">
                <dt className="text-[11.5px] text-fg-muted">{f.label}</dt>
                <dd className="mt-0.5 break-words text-[13px] font-medium text-fg">{f.value}</dd>
              </div>
            ))}
          </dl>
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
                    <div className="stagger flex flex-wrap gap-1.5">
                      {rows.map((s) => (
                        <span key={s.id} title={`Confidence ${s.confidence ?? "—"}`}>
                          <Badge tone={key === "news" ? "info" : key === "activity" ? "accent" : "neutral"}>{signalLabel(s)}</Badge>
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
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
                    <div className="stagger flex flex-wrap gap-1.5">
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
        {timeline.length > 0 && (
          <Section title="Timeline" description="Dated business events, each from a public source.">
            <ol className="stagger relative space-y-3 border-l border-border pl-4">
              {timeline.map((e) => (
                <li key={e.id} className="relative text-[13px]">
                  <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-accent" aria-hidden />
                  <span className="block text-xs tabular-nums text-fg-muted">{e.event_date ? formatDate(e.event_date) : "—"}</span>
                  <Badge tone="info">{humanize(e.signal_type)}</Badge> <span className="text-fg">{e.description}</span>
                </li>
              ))}
            </ol>
          </Section>
        )}
      </div>

      <aside className="min-w-0 space-y-5 xl:sticky xl:top-4">
        <Section title="Contact" flush>
          <ContactList contacts={contacts} />
        </Section>
        {(safeHref(c.website) || socials.length > 0) && (
          <Section title="Online">
            <div className="flex flex-wrap gap-1.5">
              {safeHref(c.website) && (
                <a
                  href={safeHref(c.website)!}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-[12.5px] font-medium transition-colors hover:border-accent/50 hover:text-accent"
                >
                  <Globe className="h-3.5 w-3.5" aria-hidden /> {c.domain ?? "Website"}
                </a>
              )}
              {socials.map(([label, url]) => (
                <a
                  key={label}
                  href={safeHref(url) ?? undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 rounded-full border border-border px-3 py-1 text-[12.5px] font-medium transition-colors hover:border-accent/50 hover:text-accent"
                >
                  {label} <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              ))}
            </div>
          </Section>
        )}
        <Section title="Locations" description={detail.locations.length ? `${detail.locations.length} on record` : undefined} flush>
          {detail.locations.length ? (
            <LocationsList locations={detail.locations} />
          ) : (
            <p className="px-4 py-4 text-[13px] text-fg-subtle">No locations recorded.</p>
          )}
        </Section>
      </aside>
    </div>
  );
}

type ContactRow = { id: string; value: string; kind: string; purpose: string | null; confidence: number | null };
const SHORTLIST: [string, number][] = [["Mobile", 2], ["WhatsApp", 1], ["Phone", 1], ["Email", 1]];

/** The company's numbers and addresses, one per real number (formatted), the best few first; the rest on demand. */
function ContactList({ contacts }: { contacts: ContactRow[] }) {
  const [all, setAll] = useState(false);
  const seen = new Set<string>();
  const unique = contacts.filter((r) => {
    const key = r.kind === "Email" ? r.value.toLowerCase() : formatPhone(r.value).replace(/[^\d]/g, "");
    return !seen.has(key) && !!seen.add(key);
  });
  if (!unique.length) return <p className="px-4 py-4 text-[13px] text-fg-subtle">No company phone or e-mail yet.</p>;
  const short = SHORTLIST.flatMap(([kind, n]) => unique.filter((r) => r.kind === kind).slice(0, n));
  const shown = all || unique.length <= short.length + 1 ? unique : short;
  return (
    <>
      <ul className="stagger divide-y divide-border">
        {shown.map((r) => {
          const email = r.kind === "Email";
          const Icon = email ? Mail : r.kind === "WhatsApp" ? MessageCircle : r.kind === "Mobile" ? Smartphone : Phone;
          const value = email ? r.value : formatPhone(r.value);
          const digits = value.replace(/[^\d+]/g, "");
          const wa = `https://wa.me/${digits.replace("+", "")}`;
          const href = email ? `mailto:${r.value}` : r.kind === "WhatsApp" ? wa : `tel:${digits}`;
          return (
            <li key={r.id} className="group flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-surface-hover/60">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                <Icon className="h-4 w-4" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <a href={href} className="block truncate text-[13px] font-medium tabular text-fg hover:text-accent hover:underline" title={r.value}>
                  {value}
                </a>
                <span className="text-[11.5px] text-fg-muted">
                  {r.kind === "Mobile" ? "Mobile · often reaches the owner or a manager" : r.purpose ? humanize(r.purpose) : r.kind}
                  {r.confidence != null && <> · {r.confidence >= 75 ? "high" : r.confidence >= 50 ? "medium" : "low"} confidence</>}
                </span>
              </span>
              {r.kind === "Mobile" && digits.startsWith("+961") && (
                <a href={wa} target="_blank" rel="noreferrer" className="text-fg-muted hover:text-accent" aria-label={`WhatsApp ${value}`} title="WhatsApp">
                  <MessageCircle className="h-4 w-4" aria-hidden />
                </a>
              )}
              <span className="opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                <CopyButton value={value} label={email ? "email" : "number"} />
              </span>
            </li>
          );
        })}
      </ul>
      {unique.length > shown.length || all ? (
        <button type="button" onClick={() => setAll(!all)} className="w-full border-t border-border px-4 py-2 text-left text-xs font-medium text-accent hover:bg-surface-hover/60">
          {all ? "Show fewer" : `Show all ${unique.length}`}
        </button>
      ) : null}
    </>
  );
}

/** The company's locations with an OpenStreetMap of the chosen one (the HQ first) and directions in Google Maps. */
function LocationsList({ locations }: { locations: CompanyDetail["locations"] }) {
  const mapped = locations.filter((l) => l.latitude != null && l.longitude != null);
  const [focus, setFocus] = useState(() => (mapped.find((l) => l.is_headquarters) ?? mapped[0])?.id ?? null);
  const shown = mapped.find((l) => l.id === focus);
  const d = 0.004; // about 400 m around the pin
  return (
    <>
      {shown && (
        <iframe
          title={`Map: ${shown.name ?? shown.address ?? "location"}`}
          className="block h-56 w-full border-0 border-b border-border"
          loading="lazy"
          referrerPolicy="strict-origin-when-cross-origin" // OpenStreetMap refuses tiles without a Referer
          src={`https://www.openstreetmap.org/export/embed.html?bbox=${shown.longitude! - d},${shown.latitude! - d},${shown.longitude! + d},${shown.latitude! + d}&layer=mapnik&marker=${shown.latitude},${shown.longitude}`}
        />
      )}
      <ul className="stagger divide-y divide-border">
        {locations.map((l) => {
          const where = [l.address, place(l.city, l.region, l.country)].filter((v) => v && v !== "—").join(", ");
          return (
            <li key={l.id} className="flex gap-3 px-4 py-3">
              <MapPin className={`mt-0.5 h-4 w-4 shrink-0 ${l.is_headquarters ? "text-accent" : "text-fg-subtle"}`} aria-hidden />
              <span className="min-w-0 flex-1 text-[13px]">
                <span className="flex flex-wrap items-center gap-1.5">
                  <span className="font-medium">{l.name ?? place(l.city, l.region, l.country)}</span>
                  {l.is_headquarters && <Badge tone="accent">HQ</Badge>}
                  {!l.is_headquarters && l.location_type && <span className="text-[11.5px] text-fg-muted">{humanize(l.location_type)}</span>}
                </span>
                {l.address && <span className="block text-xs text-fg-muted">{l.address}</span>}
                <span className="mt-1 flex flex-wrap gap-x-3 text-xs">
                  {l.phone && (
                    <a href={`tel:${l.phone.replace(/[^\d+]/g, "")}`} className="tabular text-fg hover:text-accent">
                      {l.phone}
                    </a>
                  )}
                  {l.latitude != null && l.longitude != null ? (
                    <>
                      {l.id !== focus && (
                        <button type="button" onClick={() => setFocus(l.id)} className="text-accent hover:underline">
                          Show on map
                        </button>
                      )}
                      <a href={`https://www.google.com/maps/dir/?api=1&destination=${l.latitude},${l.longitude}`} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                        Directions
                      </a>
                    </>
                  ) : (
                    where && (
                      <a href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(where)}`} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                        Find on map
                      </a>
                    )
                  )}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </>
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
  internal_seed: "TECOMSA internal",
  business_card: "Business card",
  email_signature: "Email signature",
  meeting_contact: "Meeting contact",
  contributed_contact: "Contributed by a colleague",
  open_dataset: "Wikidata",
};

/** Where a person's role is stated: "Company website", "Conference"... (each once). */
function sourceLabels(p: CompanyPerson): string[] {
  return [
    ...new Set(
      p.sources.map((s) =>
        // a licensed directory / provider by its own name: "5INDEX directory", "Lusha"
        s.source_type === "licensed_directory" ? `${(s.name ?? "Directory").replace(/\s*\(licensed directory\)$/i, "")} directory` : s.source_type === "licensed_provider" ? (s.name ?? "Lusha") : (SOURCE_LABEL[s.source_type ?? ""] ?? "Public source"),
      ),
    ),
  ];
}

/** Names a company registration lists (board, shareholders, signatories): often not the people running it day to day. */
const REGISTRATION_TITLES = new Set(["Board Member", "Shareholder", "Authorized Signatory"]);
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
  corroborated_email: "success",
  verified_email: "success",
  published_email: "info",
  business_mobile: "info",
  direct_business_phone: "info",
  whatsapp: "info",
  office_extension: "info",
  business_phone: "warning",
  high_confidence_email: "warning",
  internal_email: "info",
  delivered_email: "info",
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
          <Badge tone={best.confirmed ? "success" : (CONTACT_TONE[best.kind] ?? "neutral")}>{best.confirmed ? `✓ ${best.label}` : best.label}</Badge>
          {best.since && <span className="text-fg-subtle">{best.stale ? `${formatDate(best.since)} · may be outdated` : formatDate(best.since)}</span>}
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

/** After a call, one click on the number shown: it worked (confirmed for everyone), it's wrong (hidden), or the person
 * left. The same events as Feedback (POST /companies/{id}/contact-feedback). */
function CallResult({ companyId, person, onChanged }: { companyId: number; person: CompanyPerson; onChanged: () => void }) {
  const best = person.contacts?.[0];
  const phone = best && !best.kind.endsWith("email") ? person.phones.find((p) => p.phone === best.value) : undefined;
  const [busy, setBusy] = useState(false);
  if (!phone || best?.confirmed) return null;
  const send = async (event: string, done: string) => {
    setBusy(true);
    try {
      await api(`/companies/${companyId}/contact-feedback`, {
        method: "POST",
        body: event === "person_left_company" ? { event, company_person_id: person.id } : { event, phone_id: phone.id },
      });
      toast.success(`${person.person.full_name}: ${done}`);
      onChanged();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save the call result");
    } finally {
      setBusy(false);
    }
  };
  const chip = "rounded border border-border px-1.5 py-0.5 text-[11px] text-fg-muted hover:border-accent/50 hover:text-fg disabled:opacity-50";
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1" role="group" aria-label={`Call result for ${person.person.full_name}`}>
      <span className="text-[11px] text-fg-subtle">Called?</span>
      <button type="button" className={chip} disabled={busy} onClick={() => void send("number_confirmed", "number confirmed for everyone")}>
        ✓ Works
      </button>
      <button type="button" className={chip} disabled={busy} onClick={() => void send("wrong_number", "wrong number hidden")}>
        ✗ Wrong number
      </button>
      <button type="button" className={chip} disabled={busy} onClick={() => void send("person_left_company", "marked as left")}>
        Left the company
      </button>
    </span>
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
  const canRemove = isPrivileged(useCurrentUser());
  const [removing, setRemoving] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const remove = async () => {
    setBusy(true);
    try {
      await api(`/companies/${companyId}/people/${person.person.id}/remove`, { method: "POST", body: { reason: reason.trim() } });
      toast.success(`${person.person.full_name} removed: research and imports will not add them again`);
      setRemoving(false);
      onChanged();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not remove the person");
    } finally {
      setBusy(false);
    }
  };
  const send = async (event: string) => {
    if (event === "remove") {
      setReason("");
      setRemoving(true);
      return;
    }
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
    <>
      <ConfirmDialog
        open={removing}
        title={`Remove ${person.person.full_name} from LeadFinder?`}
        confirmLabel="Remove"
        tone="danger"
        busy={busy}
        confirmDisabled={reason.trim().length < 3}
        onConfirm={() => void remove()}
        onClose={() => setRemoving(false)}
      >
        <p className="mb-3">Their roles, emails, phones and evidence are deleted, and research or imports never add them again at this company. This can&apos;t be undone.</p>
        <Field label="Why (who asked, when, how)" htmlFor={`remove-${person.id}`}>
          <Input id={`remove-${person.id}`} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. asked by phone on 12 Oct" />
        </Field>
      </ConfirmDialog>
      <select aria-label={`Feedback on ${person.person.full_name}`} className="rounded border border-border bg-surface px-1 py-0.5 text-xs text-fg-muted" value="" onChange={(e) => void send(e.target.value)}>
        <option value="">Feedback…</option>
        {options.map((f) => (
          <option key={f.event} value={f.event}>
            {f.label}
          </option>
        ))}
        {canRemove && <option value="remove">Remove (asked to be deleted)…</option>}
      </select>
    </>
  );
}

const CONTRIBUTION_CHANNELS = [
  { value: "SALES_CONFIRMED", label: "Phone call (I confirmed it)" },
  { value: "CONTRIBUTED_BUSINESS_CONTACT", label: "Business contact I know" },
  { value: "BUSINESS_CARD", label: "Business card" },
  { value: "EMAIL_SIGNATURE", label: "Email signature" },
  { value: "MEETING_CONTACT", label: "Meeting contact" },
];

/** A business contact the user explicitly contributes: attributed to them, with who may see it. */
function AddContact({ companyId, onChanged }: { companyId: number; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({ channel: "CONTRIBUTED_BUSINESS_CONTACT", visibility: "organization" });
  const start = (channel: string) => {
    setForm({ channel, visibility: "organization" });
    setOpen(true);
  };
  const set = (key: string) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const submit = async () => {
    setSaving(true);
    try {
      const body = Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim() !== ""));
      await api(`/companies/${companyId}/contributions`, { method: "POST", body });
      toast.success(form.channel === "SALES_CONFIRMED" ? "Call saved: everyone sees this number now" : "Contact added");
      setOpen(false);
      setForm({ channel: "CONTRIBUTED_BUSINESS_CONTACT", visibility: "organization" });
      onChanged();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not add the contact");
    } finally {
      setSaving(false);
    }
  };
  if (!open) {
    return (
      <span className="flex gap-2">
        <Button variant="secondary" size="sm" onClick={() => start("SALES_CONFIRMED")}>
          <Phone className="h-3.5 w-3.5" aria-hidden /> Log a call
        </Button>
        <Button variant="ghost" size="sm" onClick={() => start("CONTRIBUTED_BUSINESS_CONTACT")}>
          Add business contact
        </Button>
      </span>
    );
  }
  const fields: [string, string][] = [["person", "Name"], ["title", "Job title"], ["email", "Work email"], ["mobile", "Business mobile"], ["phone", form.channel === "SALES_CONFIRMED" ? "Direct line" : "Office phone"], ["extension", "Extension"], ["whatsapp", "WhatsApp"]];
  return (
    <div className="space-y-3 rounded border border-border p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Source" htmlFor="contribution-channel">
          <Select id="contribution-channel" value={form.channel} onChange={set("channel")}>
            {CONTRIBUTION_CHANNELS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Who can see it" htmlFor="contribution-visibility">
          <Select id="contribution-visibility" value={form.visibility} onChange={set("visibility")}>
            <option value="organization">Everyone at TECOMSA</option>
            <option value="managers">Me and managers</option>
            <option value="private">Only me</option>
          </Select>
        </Field>
        {fields.map(([key, label]) => (
          <Field key={key} label={label} htmlFor={`contribution-${key}`}>
            <Input id={`contribution-${key}`} value={form[key] ?? ""} onChange={set(key)} />
          </Field>
        ))}
      </div>
      {form.channel === "EMAIL_SIGNATURE" && (
        <Field label="Paste the signature (only the signature block)" htmlFor="contribution-signature">
          <Textarea id="contribution-signature" rows={5} value={form.signature ?? ""} onChange={set("signature")} />
        </Field>
      )}
      <p className="text-xs text-fg-subtle">
        {form.channel === "SALES_CONFIRMED"
          ? "What the call gave you: who the manager is, their direct line / extension / mobile. Saved as confirmed by you."
          : "Business contacts only. It is recorded as contributed by you and can be removed later."}
      </p>
      <div className="flex gap-2">
        <Button size="sm" loading={saving} onClick={() => void submit()}>
          Add
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
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
        <div className="mt-4">
          <AddContact companyId={c.id} onChanged={onChanged} />
        </div>
        <div className="mt-4">
          <LushaPeople companyId={c.id} companyName={c.name} onChanged={onChanged} />
        </div>
      </Section>
    );
  }
  const keyPeople = new Map(people.filter((p) => p.is_key).map((p) => [p.department ?? "other", p]));
  const departments = KEY_DEPARTMENTS.filter((d) => keyPeople.has(d.key));
  const missing = KEY_DEPARTMENTS.filter((d) => d.always && !keyPeople.has(d.key)).map((d) => d.label);
  // The company's own line / mailbox: a fallback to reach a named person, never presented as theirs.
  const switchboard = detail.phones[0]?.phone ?? c.primary_phone ?? null;
  const generalEmail = detail.emails[0]?.email ?? null;
  const contact = (p: CompanyPerson) => (
    <>
      <BestContact person={p} switchboard={switchboard} generalEmail={generalEmail} />
      <CallResult companyId={c.id} person={p} onChanged={onChanged} />
    </>
  );
  return (
    <div className="space-y-5">
      <AddContact companyId={c.id} onChanged={onChanged} />
      <LushaPeople companyId={c.id} companyName={c.name} onChanged={onChanged} />
      <Section title="Key people" actions={state}>
        <div className="stagger grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {departments.map((d) => {
            const p = keyPeople.get(d.key);
            return (
              <div
                key={d.key}
                className={`min-w-0 rounded-lg border p-3 transition-[border-color,box-shadow] duration-200 ${p ? "border-border bg-surface hover:border-accent/40 hover:shadow-card-hover" : "border-dashed border-border-strong bg-surface-muted/40"}`}
              >
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-accent">{d.label}</p>
                {p ? (
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2.5">
                      <Avatar name={p.person.full_name} size="md" />
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-medium text-fg">{p.person.full_name}</p>
                        <p className="truncate text-xs text-fg-muted" title={p.job_title ?? undefined}>
                          {p.job_title}
                        </p>
                      </div>
                    </div>
                    {contact(p)}
                    <span className="flex flex-wrap items-center gap-2">
                      {confidence(p.confidence)}
                      <span className="text-[11px] text-fg-subtle">{sourceLabels(p).join(" · ")}</span>
                    </span>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
        {missing.length > 0 && (
          <p className={`mt-3 text-xs text-fg-subtle ${view.active ? "animate-pulse" : ""}`}>
            {view.active ? "Researching… " : researched ? "Not found yet: " : "Not researched yet: "}
            {missing.join(" · ")}
            {researched && !view.active && " (use Log a call or Lusha to fill them)"}
          </p>
        )}
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
                <span className="flex items-center gap-2.5">
                  <Avatar name={p.person.full_name} size="sm" />
                  <span className="font-medium">{p.person.full_name}</span>
                  {p.is_key && <Badge tone="accent">Key</Badge>}
                </span>
              ),
            },
            {
              key: "title",
              header: "Title",
              className: "whitespace-normal",
              cell: (p) => (
                <span className="block min-w-[220px] max-w-[320px] whitespace-normal" title={p.sources.map((s) => s.url ?? s.name).join("\n")}>
                  {p.job_title}
                  {REGISTRATION_TITLES.has(p.normalized_title ?? "") && (
                    <span title="From the company's registration: may not work there day to day">
                      {" "}
                      <Badge>Registration record</Badge>
                    </span>
                  )}
                  <span className="block text-xs text-fg-subtle">
                    {[DEPARTMENT_LABEL[p.department ?? ""] ?? humanize(p.department), humanize(p.seniority), sourceLabels(p).join(", ")].filter((v) => v && v !== "—").join(" · ")}
                  </span>
                </span>
              ),
            },
            {
              key: "status",
              header: "Status",
              cell: (p) => (
                <span className="flex items-center gap-1">
                  <Badge tone={EMPLOYMENT[p.employment_status].tone}>{EMPLOYMENT[p.employment_status].label}</Badge>
                  {confidence(p.confidence)}
                </span>
              ),
            },
            { key: "contact", header: "Contact", cell: (p) => <div className="min-w-[200px] max-w-[300px] whitespace-normal">{contact(p)}</div> },
            { key: "confirmed", header: "Confirmed", cell: (p) => (p.confirmed_at ? <span className="text-success">✓ {formatDate(p.confirmed_at)}</span> : muted("Not confirmed")) },
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

const FIT: Record<OpportunityFit["fit_level"], { label: string; tone: Tone }> = {
  high: { label: "High fit", tone: "success" },
  medium: { label: "Medium fit", tone: "info" },
  low: { label: "Low fit", tone: "neutral" },
  unknown: { label: "Not enough data", tone: "neutral" },
};

/** Odoo / Frinzo / IT fit from what LeadFinder knows (rules, every point with its evidence), best fit first. */
function Opportunity({ detail }: { detail: CompanyDetail }) {
  const order = ["high", "medium", "low", "unknown"];
  const fits = [...(detail.fit ?? [])].sort((a, b) => order.indexOf(a.fit_level) - order.indexOf(b.fit_level) || b.points - a.points);
  if (!fits.length) {
    return (
      <Section>
        <EmptyState icon={<Lightbulb />} title="No opportunity analysis yet" description="Odoo, Frinzo and IT fit appear once the company is researched." />
      </Section>
    );
  }
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {fits.map((f) => (
        <Section key={f.solution} title={f.label} actions={<Badge tone={FIT[f.fit_level].tone}>{FIT[f.fit_level].label}{f.points ? ` · ${f.points} pts` : ""}</Badge>}>
          <div className="space-y-4 text-[13px]">
            {f.note && <p className="rounded border border-border bg-surface-hover/60 px-3 py-2 text-xs text-fg">{f.note}</p>}
            <div>
              <p className="mb-1.5 text-xs font-medium text-fg-muted">Why</p>
              {f.reasons.length ? (
                <ul className="space-y-1.5">
                  {f.reasons.map((r) => (
                    <li key={r.why} className="flex gap-2">
                      <span className="tabular w-7 shrink-0 text-xs font-medium text-accent">+{r.points}</span>
                      <span>
                        {r.why}
                        <span className="block text-xs text-fg-subtle">{r.evidence}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-fg-subtle">{f.fit_level === "unknown" ? "LeadFinder knows too little yet: research the website, or check the people and sector." : "Nothing in what LeadFinder found points to this."}</p>
              )}
            </div>
            {f.pitch.length > 0 && (
              <div>
                <p className="mb-1.5 text-xs font-medium text-fg-muted">Pitch</p>
                <ul className="list-disc space-y-0.5 pl-4">
                  {f.pitch.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <p className="mb-1.5 text-xs font-medium text-fg-muted">Call</p>
              {f.people.length ? (
                <ul className="space-y-0.5">
                  {f.people.map((p) => (
                    <li key={p.id}>
                      <span className="font-medium">{p.name}</span> <span className="text-xs text-fg-muted">{p.title}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-fg-subtle">Ask for: {f.call.join(" → ")}</p>
              )}
            </div>
          </div>
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

const CONTACT_ORDER = ["Mobile", "WhatsApp", "Phone", "Email"];

export default function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const user = useCurrentUser();
  const { data, error, loading, reload } = useApi<CompanyDetail>(`/companies/${id}`);
  const users = useUsers(isPrivileged(user));
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

  async function changeOwner(owner: string) {
    setSaving(true);
    try {
      await api(`/companies/${id}/owner`, { method: "PATCH", body: { owner_user_id: owner ? Number(owner) : null } });
      toast.success(owner ? `Assigned to ${users.find((u) => String(u.id) === owner)?.name ?? "the user"}` : "Unassigned");
      await reload();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not reassign the company");
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
      <nav aria-label="Breadcrumb" className="mb-3 flex items-center gap-1.5 text-xs text-fg-muted">
        <Link href="/companies" className="hover:text-accent">
          Companies
        </Link>
        <ChevronRight className="h-3 w-3" aria-hidden />
        <span className="truncate text-fg">{displayName(c.name)}</span>
      </nav>
      <header className="relative mb-5 animate-page-in overflow-hidden rounded-xl bg-accent text-white shadow-card">
        <div className="flex flex-wrap items-start gap-4 p-5">
          <span className="shrink-0 rounded-xl bg-white p-1 shadow-sm">
            <Avatar name={displayName(c.name)} domain={c.domain} size="xl" />
          </span>
          <div className="min-w-0 flex-1 basis-[320px]">
            <h1 className="font-display text-[24px] font-semibold leading-tight" title={c.name}>
              {displayName(c.name)}
            </h1>
            {c.brief && <p className="mt-1 max-w-3xl text-[13.5px] leading-snug text-white/85">{c.brief}</p>}
            <div className="stagger mt-3 flex flex-wrap gap-1.5 text-[12px]">
              {[
                c.industry && { icon: Building2, text: c.industry },
                (c.headquarters_city || c.headquarters_country) && { icon: MapPin, text: place(c.headquarters_city, c.headquarters_country) },
                c.employee_count_estimate && { icon: Users, text: `${c.employee_count_estimate.toLocaleString()} employees` },
                c.founded_year && { icon: CalendarDays, text: `Since ${c.founded_year}` },
                { icon: Users, text: `${data.people.length} people` },
              ]
                .filter((x): x is { icon: typeof Building2; text: string } => !!x)
                .map(({ icon: Icon, text }) => (
                  <span key={text} className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-white/15 px-2.5 py-1 font-medium">
                    <Icon className="h-3 w-3 opacity-80" aria-hidden /> {text}
                  </span>
                ))}
              {safeHref(c.website) && (
                <a
                  href={safeHref(c.website)!}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-white px-2.5 py-1 font-medium text-accent transition-transform hover:-translate-y-px"
                >
                  <Globe className="h-3 w-3" aria-hidden /> {c.domain ?? "Website"}
                </a>
              )}
            </div>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto lg:justify-end">
            <Select aria-label="Status" value={c.status} disabled={saving} onChange={(e) => changeStatus(e.target.value as CompanyStatus)} className="w-44 border-white/0 bg-white text-fg">
              {COMPANY_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {COMPANY_STATUS[s].label}
                </option>
              ))}
            </Select>
            {isPrivileged(user) && (
              <OwnerSelect users={users} value={c.owner_user_id ? String(c.owner_user_id) : ""} onChange={changeOwner} allLabel="Unassigned" className="w-44 border-white/0 bg-white text-fg" disabled={saving} />
            )}
            {c.website && (
              <Button variant="secondary" onClick={refresh} disabled={saving || researching} title="Read the website and public sources again">
                <RefreshCw className={`h-3.5 w-3.5 ${researching ? "animate-spin" : ""}`} aria-hidden />
                {researching ? "Researching…" : "Refresh"}
              </Button>
            )}
            {isPrivileged(user) && (
              <button
                type="button"
                onClick={() => setConfirmDelete(true)}
                disabled={saving}
                aria-label={`Delete ${c.name}`}
                title="Delete company"
                className="flex h-9 w-9 items-center justify-center rounded-md text-white/75 transition-colors hover:bg-white/15 hover:text-white disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </button>
            )}
          </div>
        </div>
      </header>
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
      <div key={tab} role="tabpanel" className="animate-page-in">
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
