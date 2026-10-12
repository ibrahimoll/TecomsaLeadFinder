"use client";

import { Building2, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Badge, Button, Input, toast } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { CompanyLookup, CompanySearchHit } from "@/types/v2";

const DEBOUNCE_MS = 300;

function where(h: CompanySearchHit) {
  return [h.industry, [h.city, h.country].filter(Boolean).join(", ")].filter(Boolean).join(" · ");
}

/** The full lookup (database, then permitted public sources) and the pick among its candidates: a strong match
 * opens the company, anything else is kept as the result to show. */
function useCompanyLookup(country: string) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [slow, setSlow] = useState(false); // past the database: the public sources are being searched
  const [result, setResult] = useState<CompanyLookup | null>(null);

  useEffect(() => {
    if (!busy) return setSlow(false);
    const timer = setTimeout(() => setSlow(true), 1200);
    return () => clearTimeout(timer);
  }, [busy]);

  function opened(r: CompanyLookup) {
    if (!r.company?.company_id) return;
    if (r.created) toast.success("Company found.", "Researching public sources…");
    router.push(`/companies/${r.company.company_id}`);
  }

  async function lookup(q: string) {
    if (q.trim().length < 2) return;
    setBusy(true);
    setResult(null);
    try {
      const r = await api<CompanyLookup>("/companies/lookup", { method: "POST", body: { q: q.trim(), country } });
      if (r.company) opened(r);
      else setResult(r);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "The search could not be completed");
    } finally {
      setBusy(false);
    }
  }

  async function pick(lookupId: number, index: number) {
    setBusy(true);
    try {
      const r = await api<CompanyLookup>(`/companies/lookup/${lookupId}/select`, { method: "POST", body: { index } });
      if (r.company) opened(r);
      else setResult(r);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "The company could not be added");
    } finally {
      setBusy(false);
    }
  }

  return { busy, slow, result, setResult, lookup, pick };
}

/** A lookup that opened nothing: the candidates to pick from, or plainly that nothing was found. */
function LookupResult({ result, pick }: { result: CompanyLookup; pick: (lookupId: number, index: number) => void }) {
  return (
    <div className="mt-3 text-left text-[13px]" aria-live="polite">
      {result.status === "ambiguous" && result.candidates.length > 0 ? (
        <>
          <p className="mb-2 text-fg">{result.candidates.length === 1 ? "We found a possible match. Check it before adding it." : "We found multiple possible matches."}</p>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {result.candidates.map((c, i) => (
              <li key={`${c.company_id ?? "src"}-${i}`} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="min-w-0">
                  <span className="flex items-center gap-2 font-medium text-fg">
                    <Building2 className="h-3.5 w-3.5 text-fg-subtle" aria-hidden />
                    <span className="truncate">{c.name}</span>
                    {c.company_id === null && <Badge tone="neutral">{c.source ?? "Public source"}</Badge>}
                  </span>
                  <span className="block truncate text-xs text-fg-subtle">{[where(c), c.website, c.company_id === null && c.detail].filter(Boolean).join(" · ")}</span>
                </span>
                {c.company_id ? (
                  <Link href={`/companies/${c.company_id}`} className="shrink-0 text-xs font-medium text-accent hover:underline">
                    Open company
                  </Link>
                ) : (
                  c.pick_index !== null &&
                  result.lookup_id !== null && (
                    <Button size="sm" variant="secondary" onClick={() => pick(result.lookup_id!, c.pick_index!)}>
                      Add company
                    </Button>
                  )
                )}
              </li>
            ))}
          </ul>
        </>
      ) : result.status === "owned" ? (
        <p className="text-fg-muted">This company is already in LeadFinder and belongs to another lead generator. Ask a manager to reassign it if you need it.</p>
      ) : result.status === "timed_out" ? (
        <p className="text-fg-muted">The public sources did not answer in time. Try again, or try a legal name, brand or website domain.</p>
      ) : (
        <p className="text-fg-muted">
          No verified company match found in LeadFinder or the public sources.{" "}
          <span className="text-fg-subtle">Try a legal name, brand, or website domain.</span>
        </p>
      )}
    </div>
  );
}

/** The Companies list found nothing for `q`: offer the public-source lookup for it (never run on its own). */
export function PublicLookup({ q, country }: { q: string; country: string }) {
  const { busy, slow, result, setResult, lookup, pick } = useCompanyLookup(country);
  useEffect(() => setResult(null), [q, setResult]);
  return (
    <div className="flex w-full max-w-xl flex-col items-center">
      <Button onClick={() => void lookup(q)} loading={busy}>
        <Search className="h-3.5 w-3.5" aria-hidden /> {busy ? (slow ? "Searching public sources…" : "Searching…") : `Search public sources for “${q}”`}
      </Button>
      {result && !busy && <LookupResult result={result} pick={(id, i) => void pick(id, i)} />}
    </div>
  );
}

/** Direct company search: suggestions from LeadFinder's own database while typing (never a public source), the
 * full lookup (database, then permitted public sources) on Search / Enter. A strong match opens the company. */
export function CompanySearch({ country }: { country: string }) {
  const [q, setQ] = useState("");
  const [suggestions, setSuggestions] = useState<CompanySearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const { busy, slow, result, setResult, lookup, pick } = useCompanyLookup(country);
  const typed = useRef(0);

  useEffect(() => {
    const query = q.trim();
    if (query.length < 2) {
      setSuggestions([]);
      return;
    }
    const n = ++typed.current;
    const timer = setTimeout(() => {
      api<CompanySearchHit[]>("/companies/search", { query: { q: query, country, limit: 6 } })
        .then((hits) => n === typed.current && setSuggestions(hits))
        .catch(() => n === typed.current && setSuggestions([]));
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [q, country]);

  function submit(e: FormEvent) {
    e.preventDefault();
    setOpen(false);
    void lookup(q);
  }

  return (
    <div className="mb-4 rounded-xl border border-border bg-surface p-4 shadow-card">
      <form onSubmit={submit} className="flex flex-wrap items-center gap-2" role="search">
        <label htmlFor="company-search" className="text-xs font-medium text-fg">
          Search for a company
        </label>
        <div className="relative min-w-[240px] flex-1">
          <Input
            id="company-search"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOpen(true);
              setResult(null);
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
            placeholder="Anything you know: a name, website, or e.g. “hotel called Aleph in Byblos”"
            autoComplete="off"
            aria-autocomplete="list"
            aria-controls="company-search-suggestions"
            className="w-full"
          />
          {open && suggestions.length > 0 && (
            <ul id="company-search-suggestions" className="elevated absolute z-20 mt-1 w-full overflow-hidden rounded-lg bg-surface py-1">
              {suggestions.map((h) => (
                <li key={h.company_id}>
                  <Link href={`/companies/${h.company_id}`} className="flex items-baseline justify-between gap-3 px-3 py-1.5 hover:bg-surface-muted">
                    <span className="truncate text-[13px] font-medium text-fg">{h.name}</span>
                    <span className="shrink-0 truncate text-xs text-fg-subtle">{where(h)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
        <Button type="submit" loading={busy}>
          <Search className="h-3.5 w-3.5" aria-hidden /> {busy ? "Searching…" : "Search"}
        </Button>
      </form>
      {busy && <p className="mt-2 text-xs text-fg-subtle" aria-live="polite">{slow ? "Searching public sources…" : "Searching LeadFinder…"}</p>}
      {result && !busy && <LookupResult result={result} pick={(id, i) => void pick(id, i)} />}
    </div>
  );
}
