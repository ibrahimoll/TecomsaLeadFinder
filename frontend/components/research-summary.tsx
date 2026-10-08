"use client";

import clsx from "clsx";
import { AlertTriangle, ArrowRight, Briefcase, Check, CheckCircle2, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { FitScore, QualificationBadge } from "@/components/status-badges";
import { Badge, Button, toast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import type { DecisionMaker, Page, ResearchRun, ResearchRunDetail } from "@/types";

const ACTIVE = new Set(["QUEUED", "RESEARCHING", "RESEARCHED"]);
const CONTACT_ACTIVE = new Set(["PENDING", "RUNNING"]);
const SOURCE_LABEL: Record<string, string> = { FREE: "Free sources (company website)", APOLLO: "Apollo", LUSHA: "Lusha" };
const DETAIL: Record<string, string> = {
  NOT_REQUESTED: "Not requested",
  NOT_FOUND: "Not found",
  SKIPPED: "Skipped (company not qualified)",
  PENDING: "Requested — arrives later",
  DISABLED: "Not bought (paid enrichment off / not available)",
  BUDGET_LIMIT_REACHED: "Monthly credit limit reached",
  FAILED: "Provider failed — retry",
};

function stage(run: ResearchRun): string {
  if (run.status === "QUEUED") return "Queued…";
  if (run.status === "RESEARCHING") return run.reused_from_run_id ? "Reusing earlier research…" : "Reading the company website…";
  if (run.status === "RESEARCHED") return "Qualifying…";
  return "Finding the decision-maker…";
}

/** Index of the current stage, straight from the run's real status (no invented progress). */
function stageIndex(run: ResearchRun): number {
  if (run.status === "QUEUED") return 0;
  if (run.status === "RESEARCHING") return 1;
  if (run.status === "RESEARCHED") return 2;
  return 3;
}
const STAGES = ["Queued", "Website", "Qualification", "Decision-maker"];

function StageTracker({ run }: { run: ResearchRun }) {
  const current = stageIndex(run);
  return (
    <div>
      <p className="text-[13px] font-medium text-fg">
        {stage(run)}
        <span className="ml-2 text-xs font-normal text-fg-subtle">This updates by itself; you can leave the page.</span>
      </p>
      <ol className="mt-3 flex flex-wrap items-center gap-2" aria-label="Research progress">
        {STAGES.map((label, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li key={label} className="flex items-center gap-2" aria-current={active ? "step" : undefined}>
              {i > 0 && (
                <span className="h-0.5 w-8 overflow-hidden rounded-full bg-border" aria-hidden>
                  <span className={clsx("block h-full bg-success transition-[width] duration-300 ease-out", i <= current ? "w-full" : "w-0")} />
                </span>
              )}
              <span className="relative flex h-6 w-6 items-center justify-center">
                {active && <span className="absolute inset-0 animate-ping rounded-full bg-accent/25 [animation-duration:1.8s]" aria-hidden />}
                <span
                  className={clsx(
                    "relative flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold transition-colors duration-300",
                    done ? "animate-pop-in bg-success text-white" : active ? "bg-accent text-white" : "border border-border-strong text-fg-subtle",
                  )}
                >
                  {done ? <Check className="h-3 w-3" strokeWidth={3} aria-hidden /> : i + 1}
                </span>
              </span>
              <span className={clsx("text-xs", active ? "font-medium text-fg" : done ? "text-fg-muted" : "text-fg-subtle")}>{label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

const EDGE: Record<string, string> = {
  QUALIFIED: "before:bg-success",
  NEEDS_REVIEW: "before:bg-warning",
  LOW_PRIORITY: "before:bg-fg-subtle",
  INSUFFICIENT_EVIDENCE: "before:bg-border-strong",
};

/** The latest research result, right on the company screen (no need to visit the tabs). */
export function ResearchSummary({ companyId, refreshKey, onCreateOpportunity }: {
  companyId: number;
  refreshKey: number;
  onCreateOpportunity?: () => void;
}) {
  const runs = useApi<Page<ResearchRun>>("/research/runs", { company_id: companyId, page_size: 1, k: refreshKey });
  const latest = runs.data?.items[0];
  const detail = useApi<ResearchRunDetail>(latest ? `/research/runs/${latest.id}` : null);
  const personId = detail.data?.contact_summary?.person_id as number | undefined;
  const person = useApi<DecisionMaker>(personId ? `/decision-makers/${personId}` : null);
  const [busy, setBusy] = useState(false);
  const running = Boolean(latest && (ACTIVE.has(latest.status) || CONTACT_ACTIVE.has(latest.contact_status ?? "")));
  const { reload: reloadRuns } = runs;
  const { reload: reloadDetail } = detail;

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      void reloadRuns();
      void reloadDetail();
    }, 2500);
    return () => clearInterval(timer);
  }, [running, reloadRuns, reloadDetail]);

  if (!latest) return null;
  const run = detail.data;
  const q = run?.qualification;
  const summary = run?.contact_summary ?? {};

  async function retryContacts() {
    if (!run) return;
    setBusy(true);
    try {
      await api(`/research/runs/${run.id}/contacts`, { method: "POST" });
      toast.info("Retrying the decision-maker step", "Research and qualification are kept.");
      await reloadRuns();
      await reloadDetail();
    } catch (err) {
      toast.error("Could not retry", err instanceof ApiError ? err.message : undefined);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className={clsx(
        "relative mb-4 animate-page-in overflow-hidden rounded-lg border border-border bg-surface p-4 pl-5 shadow-card before:absolute before:inset-y-0 before:left-0 before:w-1",
        running ? "before:bg-accent" : (q && EDGE[q.qualification_status]) || "before:bg-border-strong",
      )}
      aria-live="polite"
    >
      {running && (
        <span className="absolute inset-x-0 top-0 block h-0.5 overflow-hidden bg-accent-soft" aria-hidden>
          <span className="absolute inset-y-0 left-0 w-1/3 animate-[loading-bar_1.2s_ease-in-out_infinite] bg-accent" />
        </span>
      )}
      {running ? (
        <StageTracker run={latest} />
      ) : (
        <div key={latest.id} className="stagger flex flex-wrap items-start gap-x-10 gap-y-3 text-[13px]">
          <div className="space-y-1">
            <p className="flex items-center gap-1.5 font-display text-[14px] font-semibold">
              {latest.status === "COMPLETED" ? <CheckCircle2 className="h-4 w-4 text-success" aria-hidden /> : <AlertTriangle className="h-4 w-4 text-warning" aria-hidden />}
              {latest.status === "COMPLETED" ? "Research complete" : latest.status.replace(/_/g, " ").toLowerCase()}
            </p>
            {q && <QualificationBadge value={q.qualification_status} />}
            {latest.reused_from_run_id && <p className="text-xs text-fg-subtle">Reused research #{latest.reused_from_run_id} (no new crawl)</p>}
            {latest.status !== "COMPLETED" && latest.error && <p className="text-xs text-fg-muted">{latest.error}</p>}
          </div>
          {q && (
            <div className="grid grid-cols-[auto_auto] items-center gap-x-3 gap-y-1.5">
              <span className="text-fg-muted">Odoo fit</span>
              <FitScore score={q.odoo_fit_score} confidence={q.odoo_confidence} />
              <span className="text-fg-muted">Frinzo fit</span>
              <FitScore score={q.frinzo_fit_score} confidence={q.frinzo_confidence} />
            </div>
          )}
          {latest.contact_source && latest.contact_status === "SKIPPED" && (
            <div className="max-w-sm space-y-1">
              <p className="font-medium">Decision-maker lookup skipped.</p>
              <p className="text-fg-muted">No Apollo/Lusha paid enrichment used — LeadFinder saved the credits.</p>
            </div>
          )}
          {latest.contact_source && latest.contact_status && latest.contact_status !== "SKIPPED" && (
            <div className="min-w-[240px] space-y-1">
              <p className="text-xs font-medium uppercase tracking-wide text-fg-subtle">Primary decision maker</p>
              {person.data ? (
                <>
                  <p className="font-display text-[14px] font-semibold">{person.data.full_name}</p>
                  <p className="text-fg-muted">{person.data.title ?? "Title unknown"}</p>
                  <p>
                    Decision-maker confidence:{" "}
                    <Badge tone={person.data.best_score >= 80 ? "success" : person.data.best_score >= 60 ? "info" : "warning"}>
                      {person.data.best_score >= 80 ? "High" : person.data.best_score >= 60 ? "Medium" : "Low"} · {person.data.best_score}/100
                    </Badge>
                  </p>
                </>
              ) : (
                <p className="text-fg-muted">{personId ? "Loading…" : "No decision-maker found in the requested role."}</p>
              )}
              <p>Work email: {summary.email === "FOUND" && person.data?.work_email ? <span className="font-medium">{person.data.work_email}</span> : DETAIL[String(summary.email ?? "NOT_REQUESTED")] ?? String(summary.email)}</p>
              <p>Phone: {summary.phone === "FOUND" && person.data?.phone ? <span className="font-medium tabular">{person.data.phone}</span> : DETAIL[String(summary.phone ?? "NOT_REQUESTED")] ?? String(summary.phone)}</p>
              <p className="text-fg-muted">Source: {SOURCE_LABEL[latest.contact_source] ?? latest.contact_source}</p>
              {Array.isArray(summary.messages) && summary.messages.length > 0 && (
                <ul className="list-disc pl-4 text-xs text-fg-muted">
                  {(summary.messages as string[]).map((m, i) => <li key={i}>{m}</li>)}
                </ul>
              )}
              {/* A free-only partial result cannot improve on retry: the website was already read. */}
              {(latest.contact_status === "FAILED" || (latest.contact_status === "PARTIAL" && latest.contact_source !== "FREE")) && (
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => void retryContacts()}>
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Retry decision-maker step
                </Button>
              )}
            </div>
          )}
          <div className="ml-auto flex flex-wrap gap-2 self-center">
            {onCreateOpportunity && q?.qualification_status === "QUALIFIED" && (
              <Button size="sm" onClick={onCreateOpportunity}>
                <Briefcase className="h-3.5 w-3.5" aria-hidden /> Create opportunity
              </Button>
            )}
            {[
              { href: `/companies/${companyId}?tab=intelligence`, label: "View intelligence" },
              { href: `/companies/${companyId}?tab=people`, label: "View decision makers" },
            ].map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className="group inline-flex h-8 items-center gap-1.5 rounded border border-border-strong bg-surface px-3 text-[12.5px] font-medium text-fg shadow-xs transition-colors hover:border-accent/40 hover:text-accent"
              >
                {l.label}
                <ArrowRight className="h-3.5 w-3.5 transition-transform duration-150 group-hover:translate-x-0.5" aria-hidden />
              </Link>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
