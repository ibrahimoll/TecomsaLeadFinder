"use client";

import { AlertTriangle, ChevronDown, ExternalLink, Mail, Phone, RefreshCw, Search, UserSearch } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  Alert,
  Avatar,
  Badge,
  Button,
  ConfirmDialog,
  CopyButton,
  EmptyState,
  ErrorState,
  Field,
  FilterPills,
  Input,
  SearchInput,
  Section,
  Select,
  Skeleton,
  toast,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { safeHref } from "@/lib/url";
import type { CompanyDetail, CompanyPeople, ProviderStatus, RevealOutcome } from "@/types";

type Person = CompanyPeople["people"][number];
type Pending = { person: Person; field: "EMAIL" | "PHONE"; provider: "APOLLO" | "LUSHA" } | null;

const CONFIDENCE_TONE = { HIGH: "success", MEDIUM: "info", LOW: "warning", UNRELIABLE: "danger" } as const;
const EMAIL_STATE: Record<Person["directory"]["email_state"], string> = {
  NOT_SEARCHED: "Not searched", PUBLIC: "Public", AVAILABLE: "Available", VERIFIED: "Verified", NOT_FOUND: "Not found",
};
const PHONE_STATE: Record<Person["directory"]["phone_state"], string> = {
  NOT_SEARCHED: "Not searched", PENDING: "Requested (arrives later)", AVAILABLE: "Available", NOT_FOUND: "Not found",
};
const COSTS: Record<string, string> = {
  APOLLO_EMAIL: "Apollo — may use 1 credit (charged only when Apollo finds the email or profile data).",
  APOLLO_PHONE: "Apollo — may use about 9 credits (8 when a mobile number is returned). The number arrives later.",
  LUSHA_EMAIL: "Lusha — may use about 2 credits (search result + email reveal).",
  LUSHA_PHONE: "Lusha — may use about 2 credits (search result + phone reveal).",
};
const SOLUTION_LABEL: Record<string, string> = { ODOO: "Odoo", FRINZO: "Frinzo" };
const ACTIVE = new Set(["QUEUED", "SEARCHING"]);

const cap = (s: string) => s.charAt(0) + s.slice(1).toLowerCase();

function Confidence({ d }: { d: Person["directory"] }) {
  const b = d.breakdown;
  return (
    <span title={`Employer ${b.company_match}/40 · employment ${b.employment}/25 · sources ${b.sources}/15 · seniority ${b.seniority}/15 · freshness ${b.freshness}/5`}>
      <Badge tone={CONFIDENCE_TONE[d.confidence_label]} dot>
        {cap(d.confidence_label)} confidence
      </Badge>
    </span>
  );
}

function SourceLinks({ person }: { person: Person }) {
  const linked = person.sources.filter((s) => s.source_url);
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {person.directory.sources.join(" + ")}
      {linked.slice(0, 2).map((s) => (
        <a key={s.id} href={safeHref(s.source_url)} target="_blank" rel="noopener noreferrer" className="inline-flex items-center text-accent hover:underline" title={s.source_url ?? undefined}>
          <ExternalLink className="h-3 w-3" aria-hidden />
          <span className="sr-only">Open source page</span>
        </a>
      ))}
    </span>
  );
}

function PersonRow({ person, onReveal }: { person: Person; onReveal: (p: Pending) => void }) {
  const d = person.directory;
  const apollo = person.sources.some((s) => s.provider === "APOLLO");
  const nameKnown = Boolean(person.last_name);
  return (
    <li className="group flex gap-3 px-4 py-3 text-[13px] transition-colors duration-150 hover:bg-surface-hover/50">
      <Avatar name={person.full_name} size="lg" />
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-display text-[14px] font-semibold">{person.full_name}</span>
          <span className="text-fg-muted">{person.title ?? "Title unknown"}</span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge>{d.department_label}</Badge>
          <Badge tone={d.employment === "CURRENT" ? "success" : "warning"}>{d.employment === "CURRENT" ? "Current" : "Employment unknown"}</Badge>
          <Confidence d={d} />
          {person.last_name_obfuscated && !person.last_name && <Badge>Surname hidden until revealed</Badge>}
          {d.relevant_for.length > 0 && (
            <span className="text-[12px] text-fg-subtle">Relevant for: {d.relevant_for.map((s) => SOLUTION_LABEL[s] ?? s).join(", ")}</span>
          )}
        </div>
        {person.needs_review && person.review_reason && (
          <p className="flex items-start gap-1.5 text-[12.5px] text-warning">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> {person.review_reason}
          </p>
        )}
        <p className="text-[12.5px] text-fg-muted">
          Source: <SourceLinks person={person} />
        </p>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
          <span className="inline-flex items-center gap-1.5">
            <Mail className="h-3.5 w-3.5 text-fg-subtle" aria-hidden />
            <span className="text-fg-muted">Email:</span>
            {person.work_email ? (
              <>
                <a href={`mailto:${person.work_email}`} className="font-medium hover:text-accent hover:underline">{person.work_email}</a>
                <CopyButton value={person.work_email} label="email" />
              </>
            ) : null}
            <Badge tone={d.email_state === "VERIFIED" ? "success" : "neutral"}>{EMAIL_STATE[d.email_state]}</Badge>
            {!person.work_email && (apollo || nameKnown) && (
              <Button size="sm" variant="secondary" onClick={() => onReveal({ person, field: "EMAIL", provider: "APOLLO" })}>Get email</Button>
            )}
            {!person.work_email && (
              <Button size="sm" variant="ghost" onClick={() => onReveal({ person, field: "EMAIL", provider: "LUSHA" })}>Try Lusha</Button>
            )}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Phone className="h-3.5 w-3.5 text-fg-subtle" aria-hidden />
            <span className="text-fg-muted">Phone:</span>
            {person.phone ? (
              person.phone_dnc ? (
                <span className="font-medium tabular">{person.phone}</span> // do-not-call: never a dial link
              ) : (
                <>
                  <a href={`tel:${person.phone.replace(/[^\d+]/g, "")}`} className="font-medium tabular hover:text-accent hover:underline">{person.phone}</a>
                  <CopyButton value={person.phone} label="phone" />
                </>
              )
            ) : null}
            <Badge>{PHONE_STATE[d.phone_state]}</Badge>
            {person.phone_dnc && <Badge tone="danger">Do not call</Badge>}
            {!person.phone && d.phone_state !== "PENDING" && (
              <Button size="sm" variant="secondary" onClick={() => onReveal({ person, field: "PHONE", provider: apollo ? "APOLLO" : "LUSHA" })}>Get phone</Button>
            )}
          </span>
        </div>
      </div>
    </li>
  );
}

function RoleSearch({ disabled, onSearch }: { disabled: boolean; onSearch: (role: string) => void }) {
  const [role, setRole] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    if (role.trim()) onSearch(role.trim());
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
      <Field label="Search a specific role" htmlFor="dm-role" hint="Synonyms are included (IT Manager → Head of IT, CIO, Systems Manager…).">
        <Input id="dm-role" value={role} maxLength={100} placeholder="e.g. IT Manager" className="w-64" onChange={(e) => setRole(e.target.value)} />
      </Field>
      <Button type="submit" variant="secondary" disabled={disabled || !role.trim()}>
        <Search className="h-3.5 w-3.5" aria-hidden /> Search role
      </Button>
    </form>
  );
}

/** "Who works at THIS company?": the company's people, found automatically from free sources (company
 *  website, Apollo's credit-free search). Emails and phones are separate, explicit actions. */
export function CompanyDecisionMakers({ company }: { company: CompanyDetail }) {
  const me = useCurrentUser();
  const privileged = isPrivileged(me);
  const [ownerId, setOwnerId] = useState<string>("");
  const { data, error, loading, reload } = useApi<CompanyPeople>(`/companies/${company.id}/decision-makers`, ownerId ? { owner_id: ownerId } : undefined);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState<Pending>(null);
  const [department, setDepartment] = useState("");
  const [query, setQuery] = useState("");
  const autoStarted = useRef(false);
  const running = Boolean(data?.runs.some((r) => ACTIVE.has(r.status)));
  const providers = useApi<ProviderStatus>(privileged ? "/enrichment/providers" : null);

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void reload(), 3000);
    return () => clearInterval(timer);
  }, [running, reload]);

  async function find(options: { override?: string; role?: string; quiet?: boolean } = {}) {
    setBusy(true);
    try {
      const out = await api<{ skipped: { reason: string }[] }>("/decision-makers/search", {
        method: "POST",
        body: { company_ids: [company.id], override_reason: options.override || undefined, role: options.role || undefined },
      });
      if (out.skipped.length) toast.info("Not searched", out.skipped[0].reason);
      else if (!options.quiet)
        toast.success(options.role ? `Searching for ${options.role}` : "Finding people", "Company website and Apollo search only — no credits are used.");
      await reload();
    } catch (err) {
      if (!options.quiet) toast.error("Could not search", err instanceof ApiError ? err.message : undefined);
    } finally {
      setBusy(false);
    }
  }

  // Opening the tab lists the company's people: the first visit (or a stale list) searches by itself.
  useEffect(() => {
    if (data?.auto_search && !autoStarted.current) {
      autoStarted.current = true;
      void find({ quiet: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.auto_search]);

  async function reveal() {
    if (!pending) return;
    setBusy(true);
    try {
      const out = await api<RevealOutcome>(`/decision-makers/${pending.person.id}/reveal`, {
        method: "POST",
        body: { field: pending.field, provider: pending.provider },
      });
      const done = out.status === "ENRICHED" || out.status === "AWAITING_WEBHOOK" || out.status === "CACHED";
      (done ? toast.success : toast.info)(out.status.replace(/_/g, " ").toLowerCase(), out.message ?? undefined);
      await reload();
    } catch (err) {
      toast.error("Not revealed", err instanceof ApiError ? err.message : undefined);
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  const current = useMemo(() => (data?.people ?? []).filter((p) => p.directory.section === "CURRENT"), [data]);
  const others = useMemo(() => (data?.people ?? []).filter((p) => p.directory.section !== "CURRENT"), [data]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return current.filter(
      (p) =>
        (!department || p.directory.department === department) &&
        (!q || [p.full_name, p.title ?? "", p.directory.department_label].some((t) => t.toLowerCase().includes(q))),
    );
  }, [current, department, query]);

  if (error) return <Section><ErrorState message={error.message} onRetry={reload} /></Section>;
  if (loading && !data) return <Skeleton className="h-48 w-full" />;
  if (!data) return null;

  const latest = data.runs[0];
  const searching = running || (busy && !pending);
  const blocked = company.is_protected && !data.eligible
    ? "TECOMSA already has a relationship with this company in Odoo: it is not searched as a new prospect."
    : !data.eligible
      ? `Phase 2 status: ${data.qualification_status ? data.qualification_status.replace(/_/g, " ").toLowerCase() : "not researched"}. People are discovered for qualified companies${privileged ? " unless you approve it below" : "; a sales manager can approve it"}.`
      : null;
  const departments = data.departments.filter((d) => d.count > 0);

  return (
    <div className="space-y-4">
      <Section
        title="Decision makers"
        description={
          current.length
            ? `${current.length} ${current.length === 1 ? "person" : "people"} found at ${company.name}. Free sources first: the company website and Apollo's credit-free search. Emails and phones only when you ask.`
            : `People who work at ${company.name}, found automatically from the company website and Apollo's credit-free search.`
        }
        actions={
          !blocked && (
            <Button variant="secondary" disabled={searching} onClick={() => void find()}>
              <RefreshCw className={searching ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} aria-hidden />
              {searching ? "Finding people…" : "Refresh people"}
            </Button>
          )
        }
      >
        {blocked && <Alert tone="info">{blocked}</Alert>}
        {blocked && privileged && !company.is_protected && (
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <Field label="Approval reason (recorded in the audit log)">
              <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Met the owner at a trade fair" className="w-80" />
            </Field>
            <Button disabled={busy || reason.trim().length < 5} onClick={() => void find({ override: reason.trim() })}>
              <UserSearch className="h-3.5 w-3.5" aria-hidden /> Approve and find people
            </Button>
          </div>
        )}
        {privileged && data.owners.length > 1 && (
          <div className="mt-3 w-60">
            <Select aria-label="Whose research" value={ownerId || String(data.owner_id ?? "")} onChange={(e) => setOwnerId(e.target.value)}>
              {data.owners.map((o) => <option key={o.id} value={o.id}>Found by {o.name}</option>)}
            </Select>
          </div>
        )}
        {current.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <FilterPills<string>
              label="Department"
              value={department}
              onChange={setDepartment}
              options={[{ value: "", label: `All (${current.length})` }, ...departments.map((d) => ({ value: d.key, label: `${d.label} (${d.count})` }))]}
            />
            <SearchInput className="w-full sm:w-60" value={query} onChange={setQuery} placeholder="Search people or titles…" label="Search people" />
          </div>
        )}
        {latest && (
          <p className="mt-3 text-[12px] text-fg-subtle">
            Last search {formatDateTime(latest.created_at)}
            {latest.initiator ? ` by ${latest.initiator.name}` : ""}
            {latest.target_roles?.role_query ? ` · role: ${String(latest.target_roles.role_query)}` : ""} ·{" "}
            {latest.providers.map((p) => `${p.provider === "WEBSITE" ? "company website" : p.provider.toLowerCase()}: ${p.status.replace(/_/g, " ").toLowerCase()}${p.people ? ` (${p.people})` : ""}`).join(" · ")}
            {providers.data && ` · Apollo ${providers.data.apollo.used}/${providers.data.apollo.limit} credits this month, paid enrichment ${providers.data.paid_enrichment_enabled ? "on" : "off"}`}
          </p>
        )}
      </Section>

      {searching && current.length === 0 && (
        <Section>
          <div className="flex items-center gap-3 py-4 text-[13px] text-fg-muted">
            <RefreshCw className="h-4 w-4 animate-spin" aria-hidden /> Finding people who work at {company.name}…
          </div>
        </Section>
      )}

      {!searching && !blocked && current.length === 0 && (latest || !data.auto_search) && (
        <Section>
          <EmptyState
            icon={<UserSearch />}
            title="No current employees or decision-makers were found for this company."
            description="The company website and the configured people sources did not list anyone who currently works here."
            action={
              <div className="flex flex-col items-center gap-3">
                <Button variant="secondary" disabled={searching} onClick={() => void find()}>
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Refresh people
                </Button>
                <RoleSearch disabled={searching} onSearch={(role) => void find({ role })} />
              </div>
            }
          />
        </Section>
      )}

      {current.length > 0 && (
        <Section flush>
          {shown.length ? (
            <ul className="stagger divide-y divide-border">
              {shown.map((p) => <PersonRow key={p.id} person={p} onReveal={setPending} />)}
            </ul>
          ) : (
            <p className="px-4 py-6 text-center text-[13px] text-fg-muted">Nobody matches this filter.</p>
          )}
          <details className="group border-t border-border px-4 py-3 text-[13px]">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 text-fg-muted transition-colors hover:text-accent [&::-webkit-details-marker]:hidden">
              <ChevronDown className="h-4 w-4 text-fg-subtle transition-transform duration-200 group-open:rotate-180" aria-hidden />
              Looking for a role that isn&apos;t listed? Search a specific role
            </summary>
            <div className="mt-3"><RoleSearch disabled={searching} onSearch={(role) => void find({ role })} /></div>
          </details>
        </Section>
      )}

      {others.length > 0 && (
        <Section flush>
          <details className="group px-4 py-3 text-[13px]">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 font-medium transition-colors hover:text-accent [&::-webkit-details-marker]:hidden">
              <ChevronDown className="h-4 w-4 text-fg-subtle transition-transform duration-200 group-open:rotate-180" aria-hidden />
              Former employees and people to review ({others.length}) — not listed as current
            </summary>
            <ul className="mt-2 space-y-1.5 text-fg-muted">
              {others.map((p) => (
                <li key={p.id}>
                  <span className="font-medium text-fg">{p.full_name}</span> — {p.title ?? "title unknown"} ·{" "}
                  {p.directory.section === "FORMER" ? "former employee" : "needs review"}
                  {p.directory.section_reason ? `: ${p.directory.section_reason}` : ""} · {p.directory.sources.join(" + ")}
                </li>
              ))}
            </ul>
          </details>
        </Section>
      )}

      <ConfirmDialog
        open={pending !== null}
        title={pending ? `${pending.field === "EMAIL" ? "Get work email" : "Get phone"} for ${pending.person.full_name}?` : ""}
        confirmLabel="Use credits and reveal"
        busy={busy}
        onConfirm={() => void reveal()}
        onClose={() => setPending(null)}
      >
        {pending && (
          <div className="space-y-2 text-[13px]">
            <p>{COSTS[`${pending.provider}_${pending.field}`]}</p>
            <p className="text-fg-muted">Only this person and this field. Data LeadFinder already has is never bought again. Monthly credit limits are enforced on the server.</p>
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}
