"use client";

import clsx from "clsx";
import { useEffect, useState } from "react";

import { Checkbox, ConfirmDialog, Field, Input, Select, toast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import type { ResearchStartResult } from "@/types";

type Source = "FREE" | "APOLLO" | "LUSHA";
type Options = { sources: Record<Source, { available: boolean; reason: string | null }>; paid_enrichment_enabled: boolean; apollo_phone_available: boolean };

const SOURCES: { key: Source; label: string; help: string }[] = [
  { key: "FREE", label: "Free only", help: "Use the company website and available public LeadFinder data. No paid provider credits will be used." },
  { key: "APOLLO", label: "Apollo", help: "Use Apollo after the company qualifies to find or enrich the requested decision-maker. Provider credits may be used for contact details." },
  { key: "LUSHA", label: "Lusha", help: "Use Lusha after the company qualifies to find or enrich the requested decision-maker. Provider credits may be used for contact details." },
];
const TARGETS: { value: string; label: string }[] = [
  { value: "AUTO", label: "Auto — Recommended" },
  { value: "OWNER_CEO", label: "Owner / CEO" },
  { value: "GENERAL_MANAGER", label: "General Manager" },
  { value: "OPERATIONS", label: "Operations" },
  { value: "FINANCE", label: "Finance" },
  { value: "IT", label: "IT / ERP" },
  { value: "MARKETING", label: "Marketing / Digital" },
  { value: "CUSTOMER_SERVICE", label: "Customer Service / CX" },
  { value: "OTHER", label: "Other" },
];
const SOURCE_KEY = "lf.research.source"; // only the source is remembered; email / phone never are

function rememberedSource(): Source {
  try {
    const value = window.localStorage.getItem(SOURCE_KEY);
    return value === "APOLLO" || value === "LUSHA" ? value : "FREE";
  } catch {
    return "FREE";
  }
}

/** "Research Company": research + qualification, then (only if it qualifies) the decision-maker
 *  and the requested contact details, from the chosen source. */
export function ResearchModal({ open, companyId, onClose, onStarted }: {
  open: boolean;
  companyId: number;
  onClose: () => void;
  onStarted: () => void;
}) {
  const { data: options } = useApi<Options>(open ? "/research/options" : null);
  const [source, setSource] = useState<Source>("FREE");
  const [target, setTarget] = useState("AUTO");
  const [custom, setCustom] = useState("");
  const [email, setEmail] = useState(false);
  const [phone, setPhone] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSource(rememberedSource());
    setTarget("AUTO");
    setCustom("");
    setEmail(false); // never remembered: paid enrichment cannot happen by accident
    setPhone(false);
  }, [open]);

  const available = (s: Source) => s === "FREE" || Boolean(options?.sources[s]?.available);
  // A remembered provider that is no longer configured falls back to Free only.
  const chosen: Source = options && !available(source) ? "FREE" : source;
  const invalid = !available(chosen) || (target === "OTHER" && !custom.trim());
  const paid = chosen !== "FREE";

  async function startResearch() {
    setBusy(true);
    try {
      const result = await api<ResearchStartResult>("/research", {
        method: "POST",
        body: {
          company_ids: [companyId],
          contact_source: chosen,
          dm_target: target,
          dm_custom_title: target === "OTHER" ? custom.trim() : undefined,
          want_email: email,
          want_phone: phone,
        },
      });
      try {
        window.localStorage.setItem(SOURCE_KEY, chosen);
      } catch {
        /* storage unavailable: nothing to remember */
      }
      if (result.skipped.length) toast.info("Not started", result.skipped[0].reason);
      else toast.success("Research started", "LeadFinder will research, qualify and then look for the decision-maker.");
      onStarted();
    } catch (err) {
      toast.error("Could not start the research", err instanceof ApiError ? err.message : undefined);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ConfirmDialog
      open={open}
      title="Research Company"
      confirmLabel={busy ? "Researching…" : "Start Research"}
      busy={busy}
      confirmDisabled={invalid || !options}
      onConfirm={() => void startResearch()}
      onClose={onClose}
    >
      <div className="space-y-4 text-[13px] text-fg">
        <p className="text-fg-muted">Research and qualify this company, then find the right decision-maker using your selected source.</p>

        <fieldset>
          <legend className="mb-1.5 text-xs font-medium">Contact source</legend>
          <div className="space-y-1.5" role="radiogroup">
            {SOURCES.map((s) => {
              const ok = available(s.key);
              return (
                <label
                  key={s.key}
                  className={clsx(
                    "flex cursor-pointer gap-2.5 rounded-md border px-3 py-2 transition-colors",
                    chosen === s.key ? "border-accent bg-accent/5" : "border-border hover:bg-surface-hover",
                    !ok && "cursor-not-allowed opacity-60 hover:bg-transparent",
                  )}
                >
                  <input
                    type="radio"
                    name="research-source"
                    className="mt-0.5 accent-[rgb(var(--accent))]"
                    checked={chosen === s.key}
                    disabled={!ok}
                    onChange={() => setSource(s.key)}
                  />
                  <span>
                    <span className="font-medium">{s.label}</span>
                    {!ok && (
                      <span className="ml-2 text-xs text-fg-subtle">
                        {options?.sources[s.key]?.reason === "Not configured" || !options ? "Not configured" : "Not available"}
                      </span>
                    )}
                    <span className="block text-xs text-fg-muted">
                      {ok
                        ? s.help
                        : options?.sources[s.key]?.reason && options.sources[s.key].reason !== "Not configured"
                          ? options.sources[s.key].reason
                          : `Ask an administrator to configure ${s.label}.`}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <Field
          label="Decision-maker"
          htmlFor="research-target"
          hint={target === "AUTO" ? "LeadFinder chooses the most relevant role based on the company's Odoo / Frinzo qualification and business evidence." : undefined}
        >
          <Select id="research-target" value={target} onChange={(e) => setTarget(e.target.value)}>
            {TARGETS.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </Select>
        </Field>
        {target === "OTHER" && (
          <Field label="Role or title" htmlFor="research-title" required error={custom.trim() ? undefined : "Enter the role or title to look for."}>
            <Input id="research-title" value={custom} maxLength={100} placeholder="Procurement Manager" onChange={(e) => setCustom(e.target.value)} />
          </Field>
        )}

        <fieldset className="space-y-1.5">
          <legend className="mb-1.5 text-xs font-medium">Contact details</legend>
          <Checkbox label="Find decision-maker" checked disabled readOnly />
          <div className="flex flex-wrap gap-x-5 gap-y-1.5">
            <Checkbox label="Work email" checked={email} onChange={(e) => setEmail(e.target.checked)} />
            <Checkbox label="Phone number" checked={phone} onChange={(e) => setPhone(e.target.checked)} />
          </div>
          {(email || phone) && !paid && (
            <p className="text-xs text-fg-muted">LeadFinder will only return contact details found through free/public sources.</p>
          )}
          {(email || phone) && paid && (
            <p className="text-xs text-fg-muted">
              Provider credits may be used only after the company qualifies.
              {phone && " Phone lookup may consume more provider credits than email lookup."}
            </p>
          )}
          {(email || phone) && paid && options && !options.paid_enrichment_enabled && (
            <p className="text-xs text-warning">Paid contact details are currently switched off by an administrator: the decision-maker will be found, but no email or phone will be bought.</p>
          )}
          {phone && chosen === "APOLLO" && options && !options.apollo_phone_available && (
            <p className="text-xs text-warning">Apollo phone lookup is not set up yet (it needs a public webhook address).</p>
          )}
        </fieldset>
      </div>
    </ConfirmDialog>
  );
}
