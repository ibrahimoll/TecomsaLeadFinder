"use client";

import { X } from "lucide-react";
import { useEffect, useState, type KeyboardEvent } from "react";

import { ConfirmDialog, Field, FilterPills, Input, toast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";

type When = "today" | "tomorrow" | "pick";

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

interface Result {
  company_id: number;
  name: string;
  status: "created" | "exists" | "failed";
  error?: string;
}

/** The selected companies -> Odoo CRM leads (title, company, country, website, e-mail, phone, tags) with a call
 * scheduled for today, tomorrow or a chosen day. Created in Odoo on the day it is sent. */
export function AddToOdoo({ open, companyIds, onClose, onDone }: { open: boolean; companyIds: number[]; onClose: () => void; onDone: () => void }) {
  const status = useApi<{ configured: boolean }>("/odoo/status");
  const odooTags = useApi<string[]>(status.data?.configured && open ? "/odoo/tags" : null);
  const [tags, setTags] = useState<string[]>([]);
  const [tagText, setTagText] = useState("");
  const [when, setWhen] = useState<When>("today");
  const [picked, setPicked] = useState(iso(new Date(Date.now() + 2 * 86_400_000)));
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const today = iso(new Date());
  const callOn = when === "today" ? today : when === "tomorrow" ? iso(new Date(Date.now() + 86_400_000)) : picked;
  const configured = status.data?.configured;

  function addTag(raw: string) {
    const t = raw.trim().replace(/,$/, "");
    if (t && !tags.some((x) => x.toLowerCase() === t.toLowerCase())) setTags((all) => [...all, t].slice(0, 10));
    setTagText("");
  }
  function onTagKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(tagText);
    } else if (e.key === "Backspace" && !tagText) setTags((all) => all.slice(0, -1));
  }

  async function send() {
    setBusy(true);
    try {
      const all = tagText.trim() ? [...tags, tagText.trim()] : tags;
      const res = await api<{ results: Result[]; created: number; exists: number; failed: number }>("/odoo/leads", {
        method: "POST",
        body: { company_ids: companyIds, tags: all, call_on: callOn, title: title.trim() || null },
      });
      const parts = [`${res.created} added to Odoo`, res.exists ? `${res.exists} already there` : "", res.failed ? `${res.failed} failed` : ""].filter(Boolean);
      (res.failed ? toast.error : toast.success)(parts.join(" · "));
      const failed = res.results.find((r) => r.status === "failed");
      if (failed) toast.error(`${failed.name}: ${failed.error ?? "could not be added"}`);
      setTags([]);
      setTitle("");
      onDone();
      onClose();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not reach Odoo");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ConfirmDialog
      open={open}
      title={`Add ${companyIds.length} compan${companyIds.length === 1 ? "y" : "ies"} to Odoo`}
      confirmLabel="Add to Odoo"
      busy={busy}
      confirmDisabled={!configured || !callOn || callOn < today}
      onConfirm={() => void send()}
      onClose={onClose}
    >
      {configured === false ? (
        <p className="text-[13px] text-fg-muted">
          Odoo is not connected yet. An administrator must fill in ODOO_BASE_URL, ODOO_DATABASE, ODOO_USERNAME and ODOO_API_KEY in the server settings.
        </p>
      ) : (
        <div className="space-y-4 text-left">
          <p className="text-[12.5px] text-fg-muted">
            Each company becomes a CRM lead created today, with its name, country, website, e-mail and phone, and a call scheduled for you.
          </p>
          <Field label="Tags" htmlFor="odoo-tags">
            <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-border-strong bg-surface px-2 py-1 focus-within:border-accent">
              {tags.map((t) => (
                <span key={t} className="inline-flex animate-pop-in items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">
                  {t}
                  <button type="button" aria-label={`Remove tag ${t}`} onClick={() => setTags((all) => all.filter((x) => x !== t))} className="hover:text-fg">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
              <input
                id="odoo-tags"
                list="odoo-tag-list"
                value={tagText}
                onChange={(e) => (e.target.value.endsWith(",") ? addTag(e.target.value) : setTagText(e.target.value))}
                onKeyDown={onTagKey}
                onBlur={() => tagText.trim() && addTag(tagText)}
                placeholder={tags.length ? "" : "e.g. Odoo, Frinzo, Hot lead (Enter to add)"}
                className="min-w-[140px] flex-1 bg-transparent py-1 text-[13px] outline-none"
              />
              <datalist id="odoo-tag-list">
                {(odooTags.data ?? []).map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
            </div>
          </Field>
          <div>
            <p className="mb-1.5 text-xs font-medium text-fg">Schedule a call</p>
            <div className="flex flex-wrap items-center gap-2">
              <FilterPills
                label="Schedule a call"
                options={[
                  { value: "today", label: "Today" },
                  { value: "tomorrow", label: "Tomorrow" },
                  { value: "pick", label: "Pick a day" },
                ]}
                value={when}
                onChange={setWhen}
              />
              {when === "pick" && <Input type="date" aria-label="Call date" min={today} value={picked} onChange={(e) => setPicked(e.target.value)} className="w-40 animate-pop-in" />}
            </div>
          </div>
          <Field label="Lead title (optional)" htmlFor="odoo-title">
            <Input id="odoo-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="The company name · use {company} in your own title" maxLength={200} />
          </Field>
        </div>
      )}
    </ConfirmDialog>
  );
}

// Odoo's address, fetched once per page load and shared by every badge (a list shows dozens).
let odooBasePromise: Promise<string | null> | null = null;
function odooBase() {
  odooBasePromise ??= api<{ url: string | null }>("/odoo/status")
    .then((s) => s.url?.replace(/\/$/, "") ?? null)
    .catch(() => null);
  return odooBasePromise;
}

const OUTCOME: Record<string, string> = {
  won: "bg-success-soft text-success",
  lost: "bg-surface-muted text-fg-muted",
  open: "bg-info-soft text-info",
};

/** "In Odoo" with the lead's stage (read back hourly); a link to the lead when Odoo's address is known. */
export function OdooBadge({ c, onDark }: { c: { odoo_lead_id?: number | null; odoo_stage?: string | null; odoo_outcome?: string | null }; onDark?: boolean }) {
  const [base, setBase] = useState<string | null>(null);
  useEffect(() => {
    if (c.odoo_lead_id) void odooBase().then(setBase);
  }, [c.odoo_lead_id]);
  if (!c.odoo_lead_id) return null;
  const label = c.odoo_outcome === "won" ? "Won in Odoo" : c.odoo_outcome === "lost" ? "Lost in Odoo" : `In Odoo${c.odoo_stage ? ` · ${c.odoo_stage}` : ""}`;
  const cls = `inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ${onDark ? "bg-white text-accent" : OUTCOME[c.odoo_outcome ?? "open"] ?? OUTCOME.open}`;
  return base ? (
    <a href={`${base}/web#id=${c.odoo_lead_id}&model=crm.lead&view_type=form`} target="_blank" rel="noopener noreferrer" className={`${cls} hover:underline`} onClick={(e) => e.stopPropagation()}>
      {label} ↗
    </a>
  ) : (
    <span className={cls}>{label}</span>
  );
}
