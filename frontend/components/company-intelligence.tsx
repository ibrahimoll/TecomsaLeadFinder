"use client";

import clsx from "clsx";
import { Check, ChevronDown, CircleHelp, ExternalLink, FileText, Globe, RefreshCw, Search, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import {
  QualificationBadge,
  ResearchStatusBadge,
  ScaleBadge,
  WebsiteStatusBadge,
} from "@/components/status-badges";
import { Alert, Badge, Button, CountUp, DescriptionList, EmptyState, ErrorState, Section, Skeleton, toast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { CompanyDetail, Page, ResearchRun, ResearchRunDetail, ResearchStartResult } from "@/types";
import { safeHref } from "@/lib/url";

const ACTIVE = new Set(["QUEUED", "RESEARCHING", "RESEARCHED"]);

function SourceLink({ url }: { url: string | null }) {
  if (!url) return null;
  let label = url;
  try {
    const u = new URL(url);
    label = u.pathname === "/" ? u.hostname : u.pathname;
  } catch {
    /* keep the raw text */
  }
  return (
    <a href={safeHref(url)} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
      {label} <ExternalLink className="h-3 w-3" aria-hidden />
    </a>
  );
}

/** Score bands: 70+ is a qualified fit (the rubric threshold), 40-69 is worth a look. */
function scoreTone(score: number) {
  return score >= 70 ? "text-success" : score >= 40 ? "text-warning" : "text-fg-subtle";
}

/**
 * Animated fit gauge (pattern from 21st.dev "Animated Radial Chart"): the ring draws in and the
 * number counts up. Label and confidence are always written out, so colour is never the only cue.
 */
function ScoreRing({ label, score, confidence }: { label: string; score: number; confidence: string }) {
  const r = 30;
  const c = 2 * Math.PI * r;
  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setDrawn(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  const conf = confidence.charAt(0) + confidence.slice(1).toLowerCase();
  return (
    <div className="flex items-center gap-3" role="img" aria-label={`${label} fit ${score} out of 100, ${conf} confidence`}>
      <div className="relative h-[76px] w-[76px] shrink-0">
        <svg viewBox="0 0 76 76" className="h-full w-full -rotate-90" aria-hidden>
          <circle cx="38" cy="38" r={r} fill="none" strokeWidth="7" className="stroke-surface-muted" />
          <circle
            cx="38"
            cy="38"
            r={r}
            fill="none"
            strokeWidth="7"
            strokeLinecap="round"
            stroke="currentColor"
            className={clsx("transition-[stroke-dashoffset] duration-500 ease-out", scoreTone(score))}
            strokeDasharray={c}
            strokeDashoffset={drawn ? c * (1 - Math.min(100, Math.max(0, score)) / 100) : c}
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center font-display text-[20px] font-semibold tabular text-fg">
          <CountUp value={score} reveal={`ring:${label}`} />
        </span>
      </div>
      <div className="leading-tight">
        <p className="font-display text-[14px] font-semibold text-fg">{label} fit</p>
        <p className="mt-0.5 text-xs text-fg-muted">{conf} confidence</p>
      </div>
    </div>
  );
}

/** Splits a reason's trailing "(source)" into a chip: a link for URLs, a plain label otherwise. */
function splitSource(reason: string): { text: string; source: string | null } {
  const m = reason.match(/^(.*\S)\s+\(([^()]+)\)$/);
  return m ? { text: m[1]!, source: m[2]! } : { text: reason, source: null };
}

function SourceChip({ source }: { source: string }) {
  let host: string | null = null;
  try {
    host = /^https?:\/\//.test(source) ? new URL(source).hostname.replace(/^www\./, "") : null;
  } catch {
    host = null;
  }
  const cls =
    "inline-flex max-w-full items-center gap-1 truncate rounded-sm bg-surface-muted px-1.5 py-px text-[11.5px] text-fg-muted ring-1 ring-inset ring-border";
  return host ? (
    <a href={safeHref(source)} target="_blank" rel="noopener noreferrer" className={clsx(cls, "transition-colors hover:text-accent hover:ring-accent/30")}>
      <Globe className="h-3 w-3 shrink-0" aria-hidden /> {host}
    </a>
  ) : (
    <span className={cls}>
      <Sparkles className="h-3 w-3 shrink-0" aria-hidden /> {source}
    </span>
  );
}

function Reasons({ items }: { items: string[] }) {
  if (!items.length)
    return (
      <p className="flex items-center gap-2 text-fg-muted">
        <CircleHelp className="h-4 w-4 text-fg-subtle" aria-hidden /> No supporting evidence found.
      </p>
    );
  return (
    <ul className="stagger space-y-2.5">
      {items.map((r, i) => {
        const { text, source } = splitSource(r);
        return (
          <li key={i} className="flex gap-2.5">
            <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-success-soft text-success" aria-hidden>
              <Check className="h-2.5 w-2.5" strokeWidth={3} />
            </span>
            <span className="min-w-0">
              <span className="block">{text}</span>
              {source && (
                <span className="mt-1 block">
                  <SourceChip source={source} />
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function scoreBar(score: number) {
  return score >= 70 ? "bg-success" : score >= 40 ? "bg-warning" : "bg-fg-subtle/60";
}

/** One product's fit: colour-coded accent, animated score bar, the reasons, then what to pitch. */
function FitCard({
  title,
  score,
  confidence,
  reasons,
  listTitle,
  items,
}: {
  title: string;
  score: number;
  confidence: string;
  reasons: string[];
  listTitle: string;
  items: { name: string; reason: string }[];
}) {
  const conf = confidence.charAt(0) + confidence.slice(1).toLowerCase();
  return (
    <section className="relative overflow-hidden rounded-lg border border-border bg-surface shadow-card">
      <span className={clsx("absolute inset-x-0 top-0 h-[3px]", scoreBar(score))} aria-hidden />
      <div className="border-b border-border px-4 pb-3 pt-4">
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="text-[14px] font-semibold">{title} fit</h3>
            <p className="text-xs text-fg-muted">{conf} confidence</p>
          </div>
          <p className={clsx("font-display text-[24px] font-semibold tabular", scoreTone(score) === "text-fg-subtle" ? "text-fg-muted" : scoreTone(score))}>
            <CountUp value={score} reveal={`fit:${title}`} />
            <span className="text-[13px] font-medium text-fg-subtle">/100</span>
          </p>
        </div>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-muted" role="img" aria-label={`${title} fit ${score} out of 100`}>
          <span className={clsx("block h-full origin-left animate-grow-x rounded-full", scoreBar(score))} style={{ width: `${Math.max(2, score)}%` }} />
        </div>
      </div>
      <div className="space-y-4 p-4 text-[13px]">
        <Reasons items={reasons} />
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-fg-subtle">{listTitle}</p>
          {items.length ? (
            <ul className="stagger mt-2 space-y-1.5">
              {items.map((m) => (
                <li key={m.name} className="rounded-md border border-border bg-surface-muted/50 px-3 py-2 transition-colors hover:border-accent/30">
                  <span className="font-medium text-fg">{m.name}</span>
                  <span className="mt-0.5 block text-xs text-fg-muted">{m.reason}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-fg-muted">None supported by the evidence yet.</p>
          )}
        </div>
      </div>
    </section>
  );
}

type Signal = ResearchRunDetail["business_signals"][number];

/** Confirmed signals up front as chips; the unknowns folded away, since most sites mention few. */
function SignalsPanel({ signals }: { signals: Signal[] }) {
  const confirmed = signals.filter((s) => s.status === "CONFIRMED");
  const unknown = signals.filter((s) => s.status !== "CONFIRMED");
  return (
    <Section title="Business signals" description="Confirmed only with evidence; otherwise unknown (never assumed absent).">
      <div className="flex items-center gap-3">
        <p className="shrink-0 text-[13px] text-fg-muted">
          <span className="font-display text-[20px] font-semibold tabular text-fg">
            <CountUp value={confirmed.length} reveal="signals" />
          </span>{" "}
          of {signals.length} confirmed
        </p>
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-muted">
          <span
            className="block h-full origin-left animate-grow-x rounded-full bg-success"
            style={{ width: `${(confirmed.length / Math.max(signals.length, 1)) * 100}%` }}
          />
        </div>
      </div>
      {confirmed.length > 0 && (
        <ul className="stagger mt-3 flex flex-wrap gap-2">
          {confirmed.map((s) => (
            <li
              key={s.signal}
              className="inline-flex items-center gap-1.5 rounded-full border border-success/25 bg-success-soft px-3 py-1 text-[12.5px] font-medium text-success"
            >
              <Check className="h-3 w-3" strokeWidth={3} aria-hidden />
              {s.label}
              {s.value && !["Stated", "Inferred"].includes(s.value) && <span className="font-normal text-success/80">· {s.value}</span>}
              {s.kind === "LEADFINDER_INFERENCE" && <span className="font-normal text-success/70">(inferred)</span>}
            </li>
          ))}
        </ul>
      )}
      {unknown.length > 0 && (
        <details className="group mt-3">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-fg-muted transition-colors hover:text-fg [&::-webkit-details-marker]:hidden">
            <CircleHelp className="h-3.5 w-3.5 text-fg-subtle" aria-hidden />
            Not found on the website ({unknown.length})
            <ChevronDown className="h-3.5 w-3.5 transition-transform duration-200 group-open:rotate-180" aria-hidden />
          </summary>
          <ul className="stagger mt-2 flex flex-wrap gap-1.5">
            {unknown.map((s) => (
              <li key={s.signal} className="rounded-full border border-dashed border-border-strong px-2.5 py-0.5 text-xs text-fg-subtle">
                {s.label}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Section>
  );
}

/** The company's latest research and qualification (Intelligence tab). */
export function CompanyIntelligence({
  company,
  onResearch,
  refreshKey = 0,
}: {
  company: CompanyDetail;
  onResearch?: () => void;
  /** Bumped by the page when research is started elsewhere (header dialog), so this tab refetches. */
  refreshKey?: number;
}) {
  const runs = useApi<Page<ResearchRun>>("/research/runs", { company_id: company.id, page_size: 10, k: refreshKey });
  const latest = runs.data?.items[0];
  const detail = useApi<ResearchRunDetail>(latest ? `/research/runs/${latest.id}` : null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const running = latest ? ACTIVE.has(latest.status) : false;
  const { reload: reloadRuns } = runs;
  const { reload: reloadDetail } = detail;

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      void reloadRuns();
      void reloadDetail();
    }, 3000);
    return () => clearInterval(timer);
  }, [running, reloadRuns, reloadDetail]);

  async function start(force: boolean) {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api<ResearchStartResult>("/research", { method: "POST", body: { company_ids: [company.id], force } });
      if (result.skipped.length) setMessage(result.skipped[0].reason);
      else toast.info("Research started", "Results appear here automatically.");
      await reloadRuns();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Could not start the research.");
    } finally {
      setBusy(false);
    }
  }

  async function retry(runId: number) {
    setBusy(true);
    try {
      await api(`/research/runs/${runId}/qualify`, { method: "POST" });
      toast.info("Qualification retried");
      await reloadRuns();
      await reloadDetail();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Could not retry the qualification.");
    } finally {
      setBusy(false);
    }
  }

  if (runs.error) return <Section><ErrorState message={runs.error.message} onRetry={reloadRuns} /></Section>;
  if (runs.loading && !runs.data) return <Skeleton className="h-48 w-full" />;

  const run = detail.data;
  const q = run?.qualification;
  const action = company.is_protected ? null : (
    <Button variant={latest ? "secondary" : "primary"} disabled={busy || running} onClick={() => (latest || !onResearch ? start(Boolean(latest)) : onResearch())}>
      {latest ? <RefreshCw className="h-3.5 w-3.5" aria-hidden /> : <Search className="h-3.5 w-3.5" aria-hidden />}
      {latest ? "Refresh research" : "Research company"}
    </Button>
  );

  return (
    <div className="space-y-4">
      {message && <Alert tone="warning">{message}</Alert>}
      {company.is_protected && (
        <Alert tone="info">TECOMSA already has a relationship with this company in Odoo, so it is not researched as a new prospect.</Alert>
      )}
      {run && q ? (
        <section className="animate-page-in overflow-hidden rounded-lg border border-border bg-surface shadow-card">
          <div className="relative grid gap-5 p-5 md:grid-cols-[auto_auto_minmax(0,1fr)] md:items-center md:gap-8">
            <ScoreRing label="Odoo" score={q.odoo_fit_score} confidence={q.odoo_confidence} />
            <ScoreRing label="Frinzo" score={q.frinzo_fit_score} confidence={q.frinzo_confidence} />
            <div className="relative min-w-0 md:border-l md:border-border md:pl-8">
              <div className="flex flex-wrap items-center gap-2">
                <QualificationBadge value={q.qualification_status} />
                <span className="text-xs text-fg-muted">
                  Priority <span className="font-medium text-fg">{q.priority.charAt(0) + q.priority.slice(1).toLowerCase()}</span>
                </span>
                <ScaleBadge value={q.scale_signal} />
              </div>
              {q.status_reason && <p className="mt-2 font-display text-[15px] font-medium leading-6 text-fg">{q.status_reason}</p>}
              {q.summary && <p className="mt-1 text-[13px] text-fg-muted">{q.summary}</p>}
              {q.scale_reasons.length > 0 && (
                <p className="mt-1 text-xs text-fg-subtle">Scale signals: {q.scale_reasons.join(" · ")}. No revenue or headcount is estimated.</p>
              )}
            </div>
          </div>
          {latest && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border bg-surface-muted/60 px-5 py-2.5 text-xs text-fg-muted">
              <ResearchStatusBadge value={latest.status} />
              <span>{latest.finished_at ? `Researched ${formatDateTime(latest.finished_at)}` : "In progress"}</span>
              <span className="tabular">{latest.pages_crawled} pages read</span>
              <span className="flex items-center gap-1.5">
                <WebsiteStatusBadge value={latest.website_status} />
                {latest.final_url && <SourceLink url={latest.final_url} />}
              </span>
              <span className="text-fg-subtle">
                {q.provider === "rules" ? "Rule-based scoring (no AI review)" : `Reviewed by ${q.provider}${q.model ? ` (${q.model})` : ""}`}
                {q.reused_from_id ? " · earlier qualification reused" : ""}
              </span>
              <span className="ml-auto">{action}</span>
            </div>
          )}
          {latest?.status === "QUALIFICATION_FAILED" && (
            <div className="flex flex-wrap items-center gap-3 border-t border-border px-5 py-3">
              <Alert tone="danger" title="Qualification failed">
                {latest.error} The website research is kept; retrying does not crawl the website again.
              </Alert>
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => retry(latest.id)}>
                Retry qualification
              </Button>
            </div>
          )}
        </section>
      ) : (
        <>
      <Section
        title="Research"
        description={
          latest ? "From the company's own website and LeadFinder's map data. Every fact links to its source." : undefined
        }
        actions={latest ? action : undefined}
      >
        {!latest && (
          <EmptyState
            icon={<Search />}
            title="No research yet"
            description={
              company.is_protected
                ? "Protected companies are not researched as new prospects."
                : "Research this company to analyse its Odoo and Frinzo fit. LeadFinder reads a few pages of its website, extracts evidence, then qualifies it."
            }
            action={action}
          />
        )}
        {latest && (
          <DescriptionList
            items={[
              { label: "Status", value: <ResearchStatusBadge value={latest.status} /> },
              { label: "Last researched", value: latest.finished_at ? formatDateTime(latest.finished_at) : "In progress" },
              { label: "Website", value: <WebsiteStatusBadge value={latest.website_status} /> },
              { label: "Website URL", value: latest.final_url ? <SourceLink url={latest.final_url} /> : latest.website_url ?? "—" },
              { label: "Pages read", value: String(latest.pages_crawled) },
              { label: "Website check", value: latest.website_detail ?? "—" },
            ]}
          />
        )}
        {latest?.status === "QUALIFICATION_FAILED" && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Alert tone="danger" title="Qualification failed">
              {latest.error} The website research is kept; retrying does not crawl the website again.
            </Alert>
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => retry(latest.id)}>
              Retry qualification
            </Button>
          </div>
        )}
        {latest?.status === "RESEARCH_FAILED" && <Alert tone="danger" title="Research failed">{latest.error}</Alert>}
      </Section>

        </>
      )}
      {running && (
        <div role="status" className="flex items-center gap-2.5 rounded-lg border border-accent/20 bg-accent-soft/60 px-4 py-2.5 text-[13px] text-fg">
          <span className="relative flex h-2.5 w-2.5" aria-hidden>
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent" />
          </span>
          Researching the website… results appear here automatically.
        </div>
      )}

      {run && q && (
        <>
          <div className="stagger grid gap-4 lg:grid-cols-2">
            <FitCard
              title="Odoo"
              score={q.odoo_fit_score}
              confidence={q.odoo_confidence}
              reasons={q.odoo_reasons}
              listTitle="Recommended modules"
              items={q.recommended_modules.map((m) => ({ name: m.module, reason: m.reason }))}
            />
            <FitCard
              title="Frinzo"
              score={q.frinzo_fit_score}
              confidence={q.frinzo_confidence}
              reasons={q.frinzo_reasons}
              listTitle="Use cases"
              items={q.frinzo_use_cases.map((u) => ({ name: u.use_case, reason: u.reason }))}
            />
          </div>

          <SignalsPanel signals={run.business_signals} />

          <Section
            title={`Evidence (${run.evidence.length})`}
            description="Each fact with the sentence it comes from and its source."
          >
            {/* Timeline: one dot per fact; red for facts the source states, grey for LeadFinder's own inferences. */}
            <ol className="stagger relative space-y-4 before:absolute before:bottom-2 before:left-[5px] before:top-2 before:w-px before:bg-border">
              {run.evidence.map((f) => {
                const rejected = q.rejected_evidence.some((r) => r.evidence === f.evidence && r.signal === f.signal);
                const inferred = f.kind === "LEADFINDER_INFERENCE";
                return (
                  <li key={f.id} className="relative pl-6 text-[13px]">
                    <span
                      className={clsx(
                        "absolute left-0 top-1 h-[11px] w-[11px] rounded-full ring-4 ring-surface",
                        rejected ? "bg-danger" : inferred ? "bg-fg-subtle" : "bg-accent",
                      )}
                      aria-hidden
                    />
                    <div className="rounded-lg border border-transparent p-2 -m-2 transition-colors hover:border-border hover:bg-surface-muted/50">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-fg">{f.label}</span>
                        {!["Stated", "Inferred"].includes(f.value) && <span className="text-fg-muted">{f.value}</span>}
                        {inferred ? <Badge>LeadFinder inference</Badge> : <Badge tone="info">Stated by source</Badge>}
                        {f.from_run && <Badge tone="warning">From research #{f.from_run}</Badge>}
                        {rejected && <Badge tone="danger">Rejected by review</Badge>}
                      </div>
                      <p className="mt-1.5 line-clamp-3 border-l-2 border-accent/30 pl-2.5 italic text-fg-muted">“{f.evidence}”</p>
                      <p className="mt-1.5 text-xs">{f.source_url ? <SourceChip source={f.source_url} /> : <SourceChip source={f.source} />}</p>
                    </div>
                  </li>
                );
              })}
            </ol>
          </Section>

          <Section title="Pages read" description="What LeadFinder read on the company's website.">
            {run.pages.filter((p) => !p.skipped).length === 0 && (
              <p className="text-[13px] text-fg-muted">No pages could be read{latest?.website_detail ? `: ${latest.website_detail}` : "."}</p>
            )}
            <ul className="stagger flex flex-wrap gap-2 text-[13px]">
              {run.pages
                .filter((p) => !p.skipped)
                .map((p) => (
                  <li
                    key={p.url}
                    className="inline-flex max-w-full items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 shadow-xs transition-[border-color,transform] hover:-translate-y-px hover:border-accent/30"
                  >
                    <FileText className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden />
                    {p.kind && <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-fg-subtle">{p.kind}</span>}
                    {p.carried_from_run ? (
                      <span className="text-fg-muted">
                        From research #{p.carried_from_run} ({p.carried_pages} pages): the website cannot be read now.
                      </span>
                    ) : (
                      <SourceLink url={p.url} />
                    )}
                  </li>
                ))}
            </ul>
          </Section>
        </>
      )}

      {runs.data && runs.data.total > 1 && (
        <Section title="Research history" flush>
          <ul className="stagger divide-y divide-border text-[13px]">
            {runs.data.items.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-1.5">
                <span className="tabular text-fg-muted">#{r.id}</span>
                <span className="tabular">{formatDateTime(r.created_at)}</span>
                <ResearchStatusBadge value={r.status} />
                {r.qualification_status && <QualificationBadge value={r.qualification_status} />}
                <WebsiteStatusBadge value={r.website_status} />
                {r.initiator && <span className="text-fg-muted">by {r.initiator.name}</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
