"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Badge, Button, Checkbox, ConfirmDialog, DataTable, SearchInput, Section, toast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { LushaCredits, LushaPeople as LushaPeopleData, LushaPerson } from "@/types/v2";

interface Query {
  q: string;
  has_phone: boolean;
  page: number;
}
type Pending = { kind: "search"; query: Query } | { kind: "reveal"; person: LushaPerson; field: "email" | "phone" };

function left(c: LushaCredits | null): string {
  if (c?.budget_left != null) return ` (${c.budget_left} left this month)`;
  if (c?.account?.remaining != null) return ` (${c.account.remaining} left on the Lusha account)`;
  return "";
}

/**
 * People Lusha has at the company for typed words ("IT manager", "CFO", "marketing"), masked until revealed. Every paid
 * search / reveal is confirmed first; the same search again (within the cache window) is free and not asked.
 */
export function LushaPeople({ companyId, companyName, onChanged }: { companyId: number; companyName: string; onChanged: () => void }) {
  const credits = useApi<LushaCredits>("/lusha/credits");
  const base = `/companies/${companyId}/lusha`;
  const [text, setText] = useState("");
  const [hasPhone, setHasPhone] = useState(false);
  const [query, setQuery] = useState<Query | null>(null);
  const [data, setData] = useState<LushaPeopleData | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const cached = (q: Query) => api<LushaPeopleData>(base, { query: { ...q } });

  useEffect(() => {
    const first = { q: "", has_phone: false, page: 0 };
    cached(first)
      .then((d) => {
        setData(d);
        if (d.searched_at) setQuery(first);
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  if (!credits.data) return null;
  if (!credits.data.configured) return <p className="text-xs text-fg-subtle">Lusha not configured: people and contacts from Lusha are not available.</p>;

  /** The same search done recently: shown free. Otherwise it is confirmed first (paid). */
  const run = async (q: Query) => {
    try {
      const hit = await cached(q);
      if (hit.fresh) {
        setData(hit);
        setQuery(q);
      } else setPending({ kind: "search", query: q });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Lusha search failed");
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run({ q: text.trim(), has_phone: hasPhone, page: 0 });
  };

  const confirm = async () => {
    if (!pending) return;
    setBusy(true);
    try {
      if (pending.kind === "search") {
        setData(await api<LushaPeopleData>(`${base}/search`, { method: "POST", body: pending.query }));
        setQuery(pending.query);
      } else {
        await api(`${base}/reveal`, { method: "POST", body: { contact_id: pending.person.id, field: pending.field } });
        toast.success(`${pending.person.name}'s ${pending.field} revealed and saved`);
        if (query) setData(await cached(query));
        onChanged();
      }
      setPending(null);
      void credits.reload();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Lusha request failed");
    } finally {
      setBusy(false);
    }
  };

  const cost = pending?.kind === "reveal" ? (pending.field === "email" ? pending.person.email_credits : pending.person.phone_credits) : (data?.search_credits_estimate ?? 25);
  const words = (q: Query | null | undefined) => (q?.q ? `“${q.q}”` : "everyone");
  const cell = (p: LushaPerson, field: "email" | "phone") => {
    const values = field === "email" ? p.emails?.map((e) => e.email) : p.phones?.map((n) => (n.do_not_call ? `${n.number} (do not call)` : n.number));
    if (values) return values.length ? <span className="text-[13px]">{values.join(", ")}</span> : <span className="text-xs text-fg-subtle">Lusha had none</span>;
    const masked = field === "email" ? p.masked_email : p.masked_phone;
    if (!masked) return <span className="text-xs text-fg-subtle">—</span>;
    if (field === "phone" && p.leadfinder_has_phone) return <Badge tone="success">Number in LeadFinder</Badge>; // never paid for
    if (field === "email" && credits.data?.phone_only) return <span className="text-fg-muted">{masked}</span>; // numbers only
    return (
      <span className="flex items-center gap-2">
        <span className="text-fg-muted">{masked}</span>
        <Button size="sm" variant="secondary" onClick={() => setPending({ kind: "reveal", person: p, field })}>
          {field === "phone" ? "Get number" : "Reveal email"}
        </Button>
      </span>
    );
  };

  return (
    <Section
      title="From Lusha"
      description={data?.searched_at ? `${words(query)}: ${data.total ?? data.people.length} found · searched ${formatDate(data.searched_at)}` : "Paid data: nothing is spent until you confirm."}
      flush
    >
      <form onSubmit={submit} className="flex flex-wrap items-center gap-3 px-4 py-3">
        <SearchInput value={text} onChange={setText} label={`Search Lusha at ${companyName}`} placeholder="Search Lusha at this company: IT manager, CFO, marketing…" className="min-w-[240px] flex-1" />
        <Checkbox label="Has phone" checked={hasPhone} onChange={(e) => setHasPhone(e.target.checked)} />
        <Button type="submit" size="sm" variant="secondary">
          Search
        </Button>
      </form>
      {data && data.people.length > 0 && (
        <DataTable
          caption="People from Lusha"
          rows={data.people}
          rowKey={(p) => p.id}
          columns={[
            {
              key: "name",
              header: "Name",
              cell: (p) => (
                <span className="flex items-center gap-2">
                  <span className="font-medium">{p.name}</span>
                  {p.person_id && <Badge tone="info">In LeadFinder</Badge>}
                </span>
              ),
            },
            { key: "title", header: "Title", cell: (p) => [p.title, p.seniority].filter(Boolean).join(" · ") || "—" },
            {
              key: "has",
              header: "Lusha has",
              cell: (p) => (
                <span className="flex gap-1">
                  {p.has_email && <Badge>Work email</Badge>}
                  {p.has_phone && <Badge>Phone</Badge>}
                </span>
              ),
            },
            { key: "email", header: "Email", cell: (p) => cell(p, "email") },
            { key: "phone", header: "Phone", cell: (p) => cell(p, "phone") },
          ]}
        />
      )}
      {data?.searched_at && !data.people.length && <p className="px-4 pb-3 text-xs text-fg-subtle">Lusha has no one for this search.</p>}
      {data?.has_more && query && (
        <div className="px-4 py-3">
          <Button size="sm" variant="ghost" onClick={() => void run({ ...query, page: query.page + 1 })}>
            Next page
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={pending !== null}
        title={
          pending?.kind === "reveal"
            ? `Reveal ${pending.person.name}'s ${pending.field === "email" ? "work email" : "phone"}?`
            : `Search Lusha at ${companyName} for ${words(pending?.query)}${pending && pending.query.page > 0 ? ` (page ${pending.query.page + 1})` : ""}?`
        }
        confirmLabel={pending?.kind === "reveal" ? (pending.field === "phone" ? "Get number" : "Reveal email") : "Search Lusha"}
        busy={busy}
        onConfirm={() => void confirm()}
        onClose={() => setPending(null)}
      >
        {cost === 0
          ? "Free: this was already revealed for TECOMSA's Lusha account."
          : pending?.kind === "reveal"
            ? `This uses about ${cost} Lusha credit${cost === 1 ? "" : "s"}${left(credits.data)}.${credits.data?.reveals_left_today != null ? ` You have ${credits.data.reveals_left_today} left today.` : ""} This can't be undone.`
            : `Lusha bills per person found: this uses up to ${cost} credits${left(credits.data)}. The results are kept, so the same search is free for a while.`}
      </ConfirmDialog>
    </Section>
  );
}
