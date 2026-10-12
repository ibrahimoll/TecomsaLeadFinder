"use client";

import clsx from "clsx";
import { Radar, Sparkles } from "lucide-react";

import { CountUp, TimeAgo } from "@/components/ui";
import type { Company } from "@/types/v2";

/** The Scout's learned score as a small ring; the reasons are its title. */
export function ScoutScore({ score, reasons, size = "md" }: { score: number; reasons?: string[] | null; size?: "sm" | "md" }) {
  const r = 15.9;
  const tone = score >= 70 ? "text-success" : score >= 40 ? "text-warning" : "text-fg-subtle";
  return (
    <span
      className={clsx("relative inline-flex shrink-0 items-center justify-center", size === "sm" ? "h-8 w-8" : "h-12 w-12")}
      title={["Scout score: how likely to become a lead", ...(reasons ?? [])].join("\n")}
    >
      <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90" aria-hidden>
        <circle cx="18" cy="18" r={r} fill="none" strokeWidth="3" className="stroke-surface-muted" />
        <circle
          cx="18"
          cy="18"
          r={r}
          fill="none"
          strokeWidth="3"
          strokeLinecap="round"
          className={clsx("stroke-current transition-[stroke-dasharray] duration-700 ease-out", tone)}
          strokeDasharray={`${(score / 100) * 2 * Math.PI * r} 999`}
        />
      </svg>
      <span className={clsx("font-display font-semibold tabular", size === "sm" ? "text-[11px]" : "text-[14px]")}>
        <CountUp value={score} />
      </span>
    </span>
  );
}

/** Profiler brief + description and the Scout's view, on the company page. Renders nothing when neither has run. */
export function AgentInsights({ c }: { c: Company }) {
  if (!c.brief && c.scout_score == null) return null;
  return (
    <section className="relative animate-page-in overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <span className="absolute inset-y-0 left-0 w-1 origin-top bg-accent" aria-hidden />
      <div className="flex flex-wrap items-start gap-5 p-5 pl-6">
        {c.brief && (
          <div className="min-w-0 flex-1 basis-[420px]">
            <p className="mb-1.5 inline-flex items-center gap-1.5 text-xs font-medium text-accent">
              <Sparkles className="h-3.5 w-3.5" aria-hidden /> What they do
            </p>
            <p className="font-display text-[16px] font-semibold leading-snug text-fg">{c.brief}</p>
            {c.profile && <p className="mt-2 text-[13px] leading-relaxed text-fg-muted">{c.profile}</p>}
            <p className="mt-3 text-[11.5px] text-fg-subtle">
              Written by the Profiler agent from the company&apos;s website{c.profiled_at && <> · <TimeAgo value={c.profiled_at} /></>}. Check before quoting.
            </p>
          </div>
        )}
        {c.scout_score != null && (
          <div className="flex min-w-[220px] flex-1 basis-[240px] gap-3 rounded-lg bg-surface-muted/60 p-3">
            <ScoutScore score={c.scout_score} reasons={c.scout_reasons} />
            <div className="min-w-0">
              <p className="inline-flex items-center gap-1.5 text-xs font-medium text-fg">
                <Radar className="h-3.5 w-3.5 text-accent" aria-hidden /> Scout: lead likelihood
              </p>
              {c.scout_reasons?.length ? (
                <ul className="stagger mt-1 space-y-0.5 text-[12px] text-fg-muted">
                  {c.scout_reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-[12px] text-fg-muted">Nothing here resembles past leads yet.</p>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
