"use client";

import clsx from "clsx";
import { Briefcase, CalendarPlus, ExternalLink, PhoneCall, RefreshCw, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";

import { Alert, Badge, Button, Checkbox, ConfirmDialog, Field, Input, Select, Textarea, toast, type Tone } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import type {
  LeadStatus,
  NextActivity,
  Opportunity,
  OpportunityDraft,
  OpportunityResult,
  SalesActivityKind,
  SalesSolution,
  SyncStatus,
} from "@/types";
import { safeHref } from "@/lib/url";

export const LEAD_STATUS: Record<LeadStatus, { label: string; tone: Tone }> = {
  NEW: { label: "New", tone: "neutral" },
  READY: { label: "Ready", tone: "info" },
  CONTACTED: { label: "Contacted", tone: "accent" },
  FOLLOW_UP: { label: "Follow-up", tone: "accent" },
  MEETING: { label: "Meeting", tone: "warning" },
  PROPOSAL: { label: "Proposal", tone: "warning" },
  WON: { label: "Won", tone: "success" },
  LOST: { label: "Lost", tone: "danger" },
  ON_HOLD: { label: "On hold", tone: "neutral" },
};
export const SYNC_STATUS: Record<SyncStatus, { label: string; tone: Tone }> = {
  NOT_SYNCED: { label: "Not in Odoo", tone: "neutral" },
  SYNCING: { label: "Creating in Odoo…", tone: "info" },
  SYNCED: { label: "In Odoo", tone: "success" },
  FAILED: { label: "Odoo sync failed", tone: "danger" },
  NEEDS_REVIEW: { label: "Needs review", tone: "warning" },
};
const KINDS: { value: SalesActivityKind; label: string }[] = [
  { value: "CALL", label: "Call" },
  { value: "EMAIL", label: "Email" },
  { value: "WHATSAPP", label: "WhatsApp" },
  { value: "LINKEDIN", label: "LinkedIn" },
  { value: "MEETING", label: "Meeting" },
  { value: "FOLLOW_UP", label: "Follow-up" },
  { value: "DEMO", label: "Demo" },
  { value: "PROPOSAL", label: "Proposal" },
  { value: "OTHER", label: "Other" },
];
const CHANNELS: SalesActivityKind[] = ["CALL", "EMAIL", "WHATSAPP", "LINKEDIN", "MEETING", "OTHER"];
const KIND_LABEL = Object.fromEntries(KINDS.map((k) => [k.value, k.label])) as Record<SalesActivityKind, string>;
const SOLUTIONS: { value: SalesSolution; label: string }[] = [
  { value: "ODOO", label: "Odoo" },
  { value: "FRINZO", label: "Frinzo" },
  { value: "BOTH", label: "Both" },
];
const PRIORITIES = ["Low", "Medium", "High", "Very high"]; // Odoo stars 0-3
const SETTABLE: LeadStatus[] = ["READY", "CONTACTED", "FOLLOW_UP", "MEETING", "PROPOSAL", "ON_HOLD", "LOST"];

const tomorrow = () => new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
const newKey = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);

export function LeadStatusBadge({ value }: { value: LeadStatus | null | undefined }) {
  if (!value) return null;
  return <Badge tone={LEAD_STATUS[value].tone}>{LEAD_STATUS[value].label}</Badge>;
}

export function SyncBadge({ value, stage }: { value: SyncStatus; stage?: string | null }) {
  return <Badge tone={SYNC_STATUS[value].tone} dot>{value === "SYNCED" && stage ? `Odoo · ${stage}` : SYNC_STATUS[value].label}</Badge>;
}

export function NextActivityText({ value }: { value: NextActivity | null | undefined }) {
  if (!value) return <span className="text-fg-subtle">No next activity</span>;
  return (
    <span className={clsx(value.overdue && "font-medium text-danger")}>
      {KIND_LABEL[value.kind ?? "FOLLOW_UP"] ?? "Follow-up"} · {value.due_date ? formatDate(value.due_date) : "—"}
      {value.overdue && " (overdue)"}
    </span>
  );
}

/** Tells the user what happened; returns true when the lead now has (or links) its Odoo opportunity. */
function report(result: OpportunityResult): void {
  const o = result.opportunity;
  const toasts: Record<string, () => void> = {
    CREATED: () => toast.success("Opportunity created in Odoo", o.title ?? undefined),
    RECONCILED: () => toast.success("Opportunity linked", "Odoo had already created it on the earlier attempt: no duplicate was made."),
    ALREADY_CREATED: () => toast.info("Already in Odoo", "This company's opportunity was created earlier."),
    IN_PROGRESS: () => toast.info("Already being created", "Another request is creating this opportunity."),
    EXISTING: () => toast.error("Existing opportunity found", "Odoo already has an open opportunity for this company. Nothing was created."),
    NEEDS_REVIEW: () => toast.info("Review needed", o.review?.message),
    FAILED: () => toast.error("Odoo sync failed", (o.sync_error ?? "") + " The lead and its research are kept."),
  };
  toasts[result.outcome]?.();
  for (const w of result.warnings) toast.info("Note", w);
}

// ---- Create Opportunity ---------------------------------------------------------------------------

export function OpportunityModal({
  open,
  companyId,
  companyName,
  onClose,
  onDone,
}: {
  open: boolean;
  companyId: number;
  companyName: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const draft = useApi<OpportunityDraft>(open ? `/companies/${companyId}/opportunity/draft` : null);
  const d = draft.data;
  const [title, setTitle] = useState("");
  const [solution, setSolution] = useState<SalesSolution>("ODOO");
  const [owner, setOwner] = useState<number | null>(null);
  const [person, setPerson] = useState<number | null>(null);
  const [value, setValue] = useState("");
  const [priority, setPriority] = useState(1);
  const [notes, setNotes] = useState("");
  const [notesEdited, setNotesEdited] = useState(false);
  const [plan, setPlan] = useState(false);
  const [kind, setKind] = useState<SalesActivityKind>("CALL");
  const [due, setDue] = useState(tomorrow());
  const [activityNote, setActivityNote] = useState("");
  const [approval, setApproval] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || !d) return;
    setTitle(d.title);
    setSolution(d.solution);
    setOwner(d.owner_id);
    setPerson(d.decision_maker_id);
    setPriority(d.priority);
    setNotes(d.notes);
    setNotesEdited(false);
    setValue("");
    setPlan(false);
    setKind("CALL");
    setDue(tomorrow());
    setActivityNote("");
    setApproval("");
  }, [open, d]);

  async function choosePerson(id: number | null) {
    setPerson(id);
    if (notesEdited) return; // never overwrite the salesperson's own text
    try {
      const next = await api<OpportunityDraft>(`/companies/${companyId}/opportunity/draft`, { query: id ? { person_id: id } : {} });
      setNotes(next.notes);
    } catch {
      /* keep the current notes */
    }
  }

  async function submit() {
    setBusy(true);
    try {
      const result = await api<OpportunityResult>(`/companies/${companyId}/opportunity`, {
        method: "POST",
        body: {
          title: title.trim() || undefined,
          solution,
          owner_id: owner ?? undefined,
          decision_maker_id: person ?? undefined,
          expected_revenue: value.trim() ? value.trim() : undefined,
          priority,
          notes,
          next_activity: plan ? { kind, due_date: due, note: activityNote.trim() || undefined } : undefined,
          approval_reason: d?.needs_approval ? approval.trim() || undefined : undefined,
        },
      });
      report(result);
      onDone();
    } catch (err) {
      toast.error("Could not create the opportunity", err instanceof ApiError ? err.message : undefined);
    } finally {
      setBusy(false);
    }
  }

  const blocked = Boolean(d?.existing) || !d?.can_create || (Boolean(d?.needs_approval) && (!d?.can_approve || !approval.trim()));
  return (
    <ConfirmDialog
      open={open}
      title="Create Opportunity"
      confirmLabel={busy ? "Creating…" : "Create Opportunity"}
      busy={busy}
      confirmDisabled={!d || blocked || !title.trim() || (plan && !due)}
      onConfirm={() => void submit()}
      onClose={onClose}
    >
      {!d ? (
        <p className="py-6 text-center text-fg-subtle">{draft.error ? draft.error.message : "Loading…"}</p>
      ) : (
        <div className="space-y-3 text-[13px] text-fg">
          {d.existing && <Alert tone="warning">Existing opportunity found — {d.existing.message} LeadFinder will not create another.</Alert>}
          {!d.can_create && <Alert tone="warning">Only this lead&apos;s salesperson or a sales manager can create its opportunity.</Alert>}
          {!d.odoo_connected && <Alert tone="info">Odoo is not connected yet: the lead is saved and can be synced to Odoo later (Retry).</Alert>}
          {d.needs_approval &&
            (d.can_approve ? (
              <Field label="Approval for sales follow-up" htmlFor="opp-approval" required hint={d.needs_approval}>
                <Input id="opp-approval" value={approval} maxLength={1000} placeholder="Why this company should be worked" onChange={(e) => setApproval(e.target.value)} />
              </Field>
            ) : (
              <Alert tone="warning">{d.needs_approval} A sales manager or admin must approve it for sales follow-up.</Alert>
            ))}
          <Field label="Company" htmlFor="opp-company">
            <Input id="opp-company" value={companyName} readOnly disabled />
          </Field>
          <Field label="Opportunity title" htmlFor="opp-title" required>
            <Input id="opp-title" value={title} maxLength={255} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Solution" htmlFor="opp-solution">
              <Select id="opp-solution" value={solution} onChange={(e) => setSolution(e.target.value as SalesSolution)}>
                {SOLUTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </Select>
            </Field>
            <Field label="Salesperson" htmlFor="opp-owner">
              <Select id="opp-owner" value={owner ?? ""} disabled={d.owners.length < 2} onChange={(e) => setOwner(Number(e.target.value))}>
                {d.owners.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </Select>
            </Field>
          </div>
          <Field label="Primary contact" htmlFor="opp-person" hint={d.people.length ? undefined : "No decision-maker found yet: the opportunity is created for the company."}>
            <Select id="opp-person" value={person ?? ""} onChange={(e) => void choosePerson(e.target.value ? Number(e.target.value) : null)}>
              <option value="">None (company only)</option>
              {d.people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}{p.title ? ` — ${p.title}` : ""}{p.needs_review ? " (needs review)" : ""}
                </option>
              ))}
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Expected value" htmlFor="opp-value">
              <Input id="opp-value" inputMode="decimal" value={value} placeholder="Optional" onChange={(e) => setValue(e.target.value.replace(/[^\d.]/g, ""))} />
            </Field>
            <Field label="Priority" htmlFor="opp-priority">
              <Select id="opp-priority" value={priority} onChange={(e) => setPriority(Number(e.target.value))}>
                {PRIORITIES.map((p, i) => <option key={p} value={i}>{p}</option>)}
              </Select>
            </Field>
          </div>
          <Checkbox label="Plan the next activity" checked={plan} onChange={(e) => setPlan(e.target.checked)} />
          {plan && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Next activity" htmlFor="opp-kind">
                <Select id="opp-kind" value={kind} onChange={(e) => setKind(e.target.value as SalesActivityKind)}>
                  {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                </Select>
              </Field>
              <Field label="Date" htmlFor="opp-due" required>
                <Input id="opp-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
              </Field>
              <div className="col-span-2">
                <Input aria-label="Activity note" value={activityNote} maxLength={4000} placeholder="e.g. Follow up on ERP requirement" onChange={(e) => setActivityNote(e.target.value)} />
              </div>
            </div>
          )}
          <Field label="Notes for Odoo" htmlFor="opp-notes" hint="LeadFinder's qualification summary — edit freely. Raw website evidence is never sent.">
            <Textarea
              id="opp-notes"
              value={notes}
              maxLength={8000}
              className="min-h-[150px] font-mono text-[12px]"
              onChange={(e) => {
                setNotes(e.target.value);
                setNotesEdited(true);
              }}
            />
          </Field>
        </div>
      )}
    </ConfirmDialog>
  );
}

// ---- Activities ------------------------------------------------------------------------------------

export function ActivityDialog({
  open,
  mode,
  companyId,
  onClose,
  onDone,
}: {
  open: boolean;
  mode: "done" | "plan";
  companyId: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const [kind, setKind] = useState<SalesActivityKind>("CALL");
  const [due, setDue] = useState(tomorrow());
  const [note, setNote] = useState("");
  const [key, setKey] = useState(newKey);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setKind(mode === "done" ? "CALL" : "FOLLOW_UP");
    setDue(tomorrow());
    setNote("");
    setKey(newKey()); // one key per dialog: a double click records one activity
  }, [open, mode]);

  async function submit() {
    setBusy(true);
    try {
      const out = await api<{ warnings: string[] }>(`/companies/${companyId}/sales-activities`, {
        method: "POST",
        body: { kind, done: mode === "done", due_date: mode === "plan" ? due : undefined, note: note.trim() || undefined, client_key: key },
      });
      toast.success(mode === "done" ? "Recorded" : "Activity planned", mode === "done" ? "Nothing was sent: this is a record." : undefined);
      for (const w of out.warnings) toast.info("Note", w);
      onDone();
    } catch (err) {
      toast.error("Could not save the activity", err instanceof ApiError ? err.message : undefined);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ConfirmDialog
      open={open}
      title={mode === "done" ? "Mark contacted" : "Add activity"}
      confirmLabel={mode === "done" ? "Record" : "Add activity"}
      busy={busy}
      confirmDisabled={mode === "plan" && !due}
      onConfirm={() => void submit()}
      onClose={onClose}
    >
      <div className="space-y-3 text-[13px] text-fg">
        <div className="grid grid-cols-2 gap-3">
          <Field label={mode === "done" ? "Channel" : "Activity"} htmlFor="act-kind">
            <Select id="act-kind" value={kind} onChange={(e) => setKind(e.target.value as SalesActivityKind)}>
              {KINDS.filter((k) => mode === "plan" || CHANNELS.includes(k.value)).map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </Select>
          </Field>
          {mode === "plan" && (
            <Field label="Due date" htmlFor="act-due" required>
              <Input id="act-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            </Field>
          )}
        </div>
        <Field label="Note" htmlFor="act-note">
          <Textarea id="act-note" value={note} maxLength={4000} className="min-h-[70px]" onChange={(e) => setNote(e.target.value)} />
        </Field>
        <p className="text-xs text-fg-subtle">LeadFinder records activities only. It never sends calls, emails or messages.</p>
      </div>
    </ConfirmDialog>
  );
}

// ---- The company's opportunity card -----------------------------------------------------------------

export function useOpportunity(companyId: number, refreshKey: number) {
  const state = useApi<{ opportunity: Opportunity | null }>(`/companies/${companyId}/opportunity`);
  const { reload } = state;
  useEffect(() => {
    if (refreshKey) void reload();
  }, [refreshKey, reload]);
  return state;
}

export function OpportunityCard({
  companyId,
  opportunity,
  onCreate,
  onChanged,
}: {
  companyId: number;
  opportunity: Opportunity | null | undefined;
  onCreate: () => void;
  onChanged: () => void;
}) {
  const me = useCurrentUser();
  const privileged = isPrivileged(me);
  // Reassignment choices (managers / admins): the same list the Create Opportunity modal offers.
  const owners = useApi<OpportunityDraft>(privileged && opportunity && !opportunity.limited ? `/companies/${companyId}/opportunity/draft` : null);
  const [dialog, setDialog] = useState<"done" | "plan" | null>(null);
  const [busy, setBusy] = useState(false);
  const o = opportunity;
  if (!o) return null;

  async function complete(id: number) {
    setBusy(true);
    try {
      const out = await api<{ warnings: string[] }>(`/sales-activities/${id}/done`, { method: "POST" });
      toast.success("Marked done");
      for (const w of out.warnings) toast.info("Note", w);
      onChanged();
    } catch (err) {
      toast.error("Could not update the activity", err instanceof ApiError ? err.message : undefined);
    } finally {
      setBusy(false);
    }
  }


  async function run(path: string, body: object = {}, method: "POST" | "PATCH" = "POST") {
    setBusy(true);
    try {
      report(await api<OpportunityResult>(`/companies/${companyId}/opportunity${path}`, { method, body }));
      onChanged();
    } catch (err) {
      toast.error("Could not update the opportunity", err instanceof ApiError ? err.message : undefined);
    } finally {
      setBusy(false);
    }
  }

  if (o.limited) {
    return (
      <section className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface px-5 py-3 text-[13px] shadow-xs">
        <Briefcase className="h-4 w-4 text-fg-subtle" aria-hidden />
        <span className="font-medium">This company already has an Odoo opportunity.</span>
        {o.sync_status === "SYNCED" && <SyncBadge value="SYNCED" stage={o.odoo_stage} />}
        <span className="text-fg-subtle">Its salesperson&apos;s notes, research and activities stay private.</span>
      </section>
    );
  }

  const synced = o.sync_status === "SYNCED";
  const review = o.review;
  const next = o.next_activity;
  return (
    <section className="mb-5 rounded-lg border border-border bg-surface shadow-xs" aria-label="Odoo opportunity">
      <header className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-3">
        <Briefcase className="h-4 w-4 text-accent" aria-hidden />
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-fg-subtle">Odoo opportunity</h2>
        <SyncBadge value={o.sync_status} stage={o.odoo_stage} />
        {o.lead_status && <LeadStatusBadge value={o.lead_status} />}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {o.odoo_url && (
            <a href={safeHref(o.odoo_url)} target="_blank" rel="noopener noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded border border-border-strong bg-surface px-3 text-[12.5px] font-medium shadow-xs hover:border-accent/40 hover:text-accent">
              Open in Odoo <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          )}
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => setDialog("plan")}>
            <CalendarPlus className="h-3.5 w-3.5" aria-hidden /> Add activity
          </Button>
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => setDialog("done")}>
            <PhoneCall className="h-3.5 w-3.5" aria-hidden /> Mark contacted
          </Button>
          {synced && (
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => void run("/refresh")}>
              <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Refresh Odoo status
            </Button>
          )}
          {(o.sync_status === "NOT_SYNCED") && (
            <Button size="sm" disabled={busy} onClick={onCreate}>
              <Briefcase className="h-3.5 w-3.5" aria-hidden /> Create opportunity
            </Button>
          )}
        </div>
      </header>
      <div className="space-y-3 px-5 py-4 text-[13px]">
        {o.sync_status === "FAILED" && (
          <Alert tone="danger">
            <span className="font-medium">Odoo sync failed.</span> {o.sync_error} Your research, qualification and contacts are kept.
            <span className="mt-2 flex gap-2">
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => void run("/retry")}>
                <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Retry
              </Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={onCreate}>Edit and retry</Button>
            </span>
          </Alert>
        )}
        {o.sync_status === "NEEDS_REVIEW" && review && (
          <Alert tone="warning">
            <span className="font-medium">{review.kind === "EXISTING_OPPORTUNITY" ? "Existing opportunity found." : "Possible duplicate — review before creating."}</span>{" "}
            {review.message}
            <ul className="mt-2 space-y-1.5">
              {review.candidates.map((c, i) => (
                <li key={c.id ?? i} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{c.name ?? `#${c.id}`}</span>
                  {[c.stage, c.salesperson, c.city, c.website, c.phone].filter(Boolean).map((x) => <span key={x} className="text-fg-muted">· {x}</span>)}
                  {c.url && <a href={safeHref(c.url)} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">Open in Odoo</a>}
                  {review.kind === "POSSIBLE_PARTNER" && c.id && (
                    <Button size="sm" variant="secondary" disabled={busy} onClick={() => void run("/retry", { partner_id: c.id })}>Use this company</Button>
                  )}
                </li>
              ))}
            </ul>
            <span className="mt-2 flex flex-wrap gap-2">
              {review.kind === "POSSIBLE_PARTNER" && (
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => void run("/retry", { create_partner: true })}>It&apos;s a different company: create it</Button>
              )}
              {review.kind === "POSSIBLE_OPPORTUNITY" && (
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => void run("/retry", { create_anyway: true })}>Different opportunity: create ours</Button>
              )}
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run("/retry")}>Check again</Button>
            </span>
          </Alert>
        )}
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
          {[
            ["Opportunity", o.title ?? "Not created yet"],
            ["Stage", synced ? `${o.odoo_stage ?? "—"}${o.odoo_state && o.odoo_state !== "open" ? ` (${o.odoo_state})` : ""}` : "—"],
            ["Salesperson", o.odoo_salesperson ?? o.owner?.name ?? "—"],
            ["Primary contact", o.primary_contact ? `${o.primary_contact.name}${o.primary_contact.title ? ` — ${o.primary_contact.title}` : ""}` : "None (company only)"],
          ].map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-[11.5px] text-fg-subtle">{label}</dt>
              <dd className="truncate font-medium">{value}</dd>
            </div>
          ))}
          <div>
            <dt className="text-[11.5px] text-fg-subtle">Next activity</dt>
            <dd className="font-medium">
              {next ? <NextActivityText value={next} /> : o.odoo_next_activity ? `${o.odoo_next_activity.type ?? "Activity"} · ${formatDate(o.odoo_next_activity.date)} (Odoo)` : <NextActivityText value={null} />}
              {next && (
                <Button size="sm" variant="ghost" className="ml-2" disabled={busy} onClick={() => void complete(next.id)}>Done</Button>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-[11.5px] text-fg-subtle">Lead status</dt>
            <dd>
              <Select
                aria-label="Lead status"
                className="h-8 w-[150px]"
                value={o.lead_status}
                disabled={busy}
                onChange={(e) => void run("", { lead_status: e.target.value }, "PATCH")}
              >
                {/* WON is only ever read from Odoo; once synced, so is LOST. */}
                {[...new Set<LeadStatus>([...SETTABLE, o.lead_status as LeadStatus])].map((s) => (
                  <option key={s} value={s} disabled={!SETTABLE.includes(s) || (synced && s === "LOST" && o.lead_status !== "LOST")}>
                    {LEAD_STATUS[s].label}
                  </option>
                ))}
              </Select>
            </dd>
          </div>
          {privileged && owners.data && (
            <div>
              <dt className="text-[11.5px] text-fg-subtle">Reassign</dt>
              <dd>
                <Select aria-label="Reassign to" className="h-8 w-[180px]" value={o.owner?.id ?? ""} disabled={busy} onChange={(e) => void run("", { owner_id: Number(e.target.value) }, "PATCH")}>
                  {owners.data.owners.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                </Select>
              </dd>
            </div>
          )}
        </dl>
        {synced && <p className="text-xs text-fg-subtle">Odoo is the CRM of record for this opportunity: stage, salesperson and won / lost come from Odoo{o.last_sync_at ? ` (read ${formatDate(o.last_sync_at)})` : ""}.</p>}
      </div>
      <ActivityDialog
        open={dialog !== null}
        mode={dialog ?? "plan"}
        companyId={companyId}
        onClose={() => setDialog(null)}
        onDone={() => {
          setDialog(null);
          onChanged();
        }}
      />
    </section>
  );
}
