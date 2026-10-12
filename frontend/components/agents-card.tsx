"use client";

import clsx from "clsx";
import { Radar, Sparkles, type LucideIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { CountUp, TimeAgo } from "@/components/ui";
import { useApi } from "@/lib/api";

interface AgentsStatus {
  enabled: boolean;
  model: string;
  model_ready: boolean;
  profiler: { profiled: number; unclear: number; waiting: number; to_research: number; industries_fixed: number; last_run_at: string | null };
  scout: { leads: number; not_leads: number; min_labels: number; scored: number; searches_started: number };
}

function Agent({ icon: Icon, name, state, live, children }: { icon: LucideIcon; name: string; state: string; live: boolean; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center gap-2.5">
        <span className="relative flex h-9 w-9 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <Icon className="h-[18px] w-[18px]" aria-hidden />
          {live && (
            <span className="absolute -right-0.5 -top-0.5 flex h-2.5 w-2.5" aria-hidden>
              <span className="absolute inset-0 animate-ping rounded-full bg-success/70" />
              <span className="relative h-2.5 w-2.5 rounded-full border-2 border-surface bg-success" />
            </span>
          )}
        </span>
        <div className="min-w-0">
          <p className="font-display text-[14px] font-semibold">{name}</p>
          <p className={clsx("text-xs", live ? "text-success" : "text-fg-muted")}>{state}</p>
        </div>
      </div>
      <div className="mt-3 text-[12.5px] text-fg-muted">{children}</div>
    </div>
  );
}

const Num = ({ v, k }: { v: number; k: string }) => (
  <span className="font-medium tabular text-fg">
    <CountUp value={v} reveal={`agents:${k}`} />
  </span>
);

/** The two background agents: what they have done and what they are waiting for. Live while the Profiler works. */
export function AgentsCard() {
  const { data, reload } = useApi<AgentsStatus>("/agents/status");
  const working = !!data?.model_ready && data.profiler.waiting > 0;
  useEffect(() => {
    if (!working) return;
    const t = setInterval(() => void reload(), 15_000);
    return () => clearInterval(t);
  }, [working, reload]);
  if (!data) return null;
  const p = data.profiler;
  const s = data.scout;
  const trained = s.leads >= s.min_labels && s.not_leads >= s.min_labels;
  return (
    <section className="animate-page-in">
      <h2 className="mb-3 font-display text-[15px] font-semibold">Agents</h2>
      <div className="stagger grid gap-3 sm:grid-cols-2">
        <Agent
          icon={Sparkles}
          name="Profiler"
          live={working}
          state={!data.enabled ? "Off" : !data.model_ready ? `Waiting for the local model (${data.model})` : working ? `Writing profiles · ${p.waiting} to go` : "Up to date"}
        >
          <p>
            <Num v={p.profiled} k="profiled" /> companies described from their website
            {p.industries_fixed > 0 && (
              <>
                {" "}· <Num v={p.industries_fixed} k="industries" /> moved out of “Other”
              </>
            )}
          </p>
          <p className="mt-1">
            {p.to_research > 0 ? (
              <>
                <Num v={p.to_research} k="toresearch" /> websites still to read (it queues a few every hour)
              </>
            ) : (
              "Every company with a website has been read."
            )}
          </p>
          {p.last_run_at && (
            <p className="mt-1 text-fg-subtle">
              Last profile <TimeAgo value={p.last_run_at} /> · runs on this machine, nothing is sent outside
            </p>
          )}
        </Agent>
        <Agent icon={Radar} name="Scout" live={false} state={!data.enabled ? "Off" : trained ? `Learning from ${s.leads + s.not_leads} outcomes` : "Learning: needs more outcomes"}>
          {trained ? (
            <p>
              Scores <Num v={s.scored} k="scored" /> companies from <Num v={s.leads} k="leads" /> leads and <Num v={s.not_leads} k="notleads" /> non-leads ·{" "}
              <Num v={s.searches_started} k="searches" /> lookalike searches started
            </p>
          ) : (
            <>
              <p>
                Mark companies as <span className="font-medium text-fg">Qualified / Meeting / Working</span> or{" "}
                <span className="font-medium text-fg">Not interested</span>: it learns what a good lead looks like from at least {s.min_labels} of each.
              </p>
              <div className="mt-2 space-y-1.5">
                {[
                  { label: "Leads", v: s.leads },
                  { label: "Not interested", v: s.not_leads },
                ].map((row) => (
                  <div key={row.label} className="flex items-center gap-2">
                    <span className="w-24 text-xs">{row.label}</span>
                    <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-muted">
                      <span className="block h-full origin-left animate-grow-x rounded-full bg-accent" style={{ width: `${Math.min(100, (row.v / s.min_labels) * 100)}%` }} />
                    </span>
                    <span className="w-10 text-right text-xs tabular">
                      {Math.min(row.v, s.min_labels)}/{s.min_labels}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Agent>
      </div>
    </section>
  );
}
