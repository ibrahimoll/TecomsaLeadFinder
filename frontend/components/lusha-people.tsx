"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Badge, Button, Checkbox, ConfirmDialog, DataTable, SearchInput, Section, Select, toast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { LushaCredits, LushaPeople as LushaPeopleData, LushaPerson } from "@/types/v2";

interface Query {
  q: string;
  has_phone: boolean;
  page: number;
}
type Pending = { kind: "search"; query: Query } | { kind: "reveal"; person: LushaPerson; field: "email" | "phone" };

/** The roles TECOMSA sells to, as one-click filters of the loaded list (free). */
const ROLES = {
  owner: { label: "Owner", words: ["owner", "founder", "co-founder", "chairman", "partner", "proprietor"] },
  gm: { label: "General Manager", words: ["general manager", "gm", "managing director", "ceo", "chief executive"] },
  finance: { label: "Finance", words: ["finance", "financial", "cfo", "accounting", "accountant", "controller", "treasury"] },
  operations: { label: "Operations", words: ["operations", "coo", "supply chain", "logistics", "procurement", "purchasing", "production", "plant"] },
  it: { label: "IT", words: ["information technology", "it", "cio", "cto", "technology", "systems"] },
  marketing: { label: "Marketing", words: ["marketing", "cmo", "brand", "digital", "social media", "communications", "growth", "crm"] },
  sales: { label: "Sales", words: ["sales", "commercial", "business development"] },
  service: { label: "Customer service", words: ["customer service", "customer care", "customer experience", "call center", "contact center", "support"] },
} as const;
type Target = keyof typeof ROLES;
/** Who decides, per product, in the order to call them (the list is sorted the same way). */
const PRODUCTS: Record<string, { label: string; roles: Target[] }> = {
  odoo: { label: "Odoo ERP", roles: ["owner", "gm", "finance", "operations", "it"] },
  it: { label: "IT solutions", roles: ["it", "owner", "gm"] },
  // Frinzo (frinzo.com): WhatsApp / Instagram / SMS / Facebook campaigns and communication automation
  frinzo: { label: "Frinzo", roles: ["marketing", "owner", "gm", "sales", "service"] },
};

function targetsOf(p: LushaPerson): Target[] {
  const hay = ` ${[p.title, p.seniority, ...(p.departments ?? [])].join(" ").toLowerCase().replace(/[^a-z-]+/g, " ")} `;
  return (Object.keys(ROLES) as Target[]).filter((k) => ROLES[k].words.some((w) => hay.includes(` ${w} `)));
}

function left(c: LushaCredits | null): string {
  if (c?.budget_left != null) return ` (${c.budget_left} left this month)`;
  if (c?.account?.remaining != null) return ` (${c.account.remaining} left on the Lusha account)`;
  return "";
}

/**
 * The people Lusha has at the company, masked until revealed: loaded once (a confirmed, paid search kept for the cache
 * window), then filtered for free as the user types ("IT", "manager", "marketing"). Every reveal is confirmed first.
 */
export function LushaPeople({ companyId, companyName, onChanged }: { companyId: number; companyName: string; onChanged: () => void }) {
  const credits = useApi<LushaCredits>("/lusha/credits");
  const base = `/companies/${companyId}/lusha`;
  const [text, setText] = useState("");
  const [hasPhone, setHasPhone] = useState(false);
  const [target, setTarget] = useState<Target | null>(null);
  const [product, setProduct] = useState("odoo");
  const roles = PRODUCTS[product].roles;
  const [query, setQuery] = useState<Query | null>(null);
  const [data, setData] = useState<LushaPeopleData | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const cached = (q: Query) => api<LushaPeopleData>(base, { query: { ...q } });
  /** Pages 0..last of a search from the cache (free), as one list. */
  const pages = async (q: Query) => {
    const all = await Promise.all(Array.from({ length: q.page + 1 }, (_, page) => cached({ ...q, page })));
    return { ...all[all.length - 1], people: all.flatMap((d) => d.people) };
  };

  // The company's whole Lusha list (one paid search, kept for the cache window): typing filters it for free.
  const everyone: Query = { q: "", has_phone: false, page: 0 };
  useEffect(() => {
    cached(everyone)
      .then((d) => {
        setData(d);
        if (d.searched_at) setQuery(everyone);
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
        setData(await pages(q));
        setQuery(q);
      } else setPending({ kind: "search", query: q });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Lusha search failed");
    }
  };
  const submit = (e: FormEvent) => e.preventDefault(); // typing filters the loaded list: nothing to send

  const confirm = async () => {
    if (!pending) return;
    setBusy(true);
    try {
      if (pending.kind === "search") {
        await api<LushaPeopleData>(`${base}/search`, { method: "POST", body: pending.query });
        setData(await pages(pending.query));
        setQuery(pending.query);
      } else {
        await api(`${base}/reveal`, { method: "POST", body: { contact_id: pending.person.id, field: pending.field } });
        toast.success(`${pending.person.name}'s ${pending.field} revealed and saved`);
        if (query) setData(await pages(query));
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

  const terms = text.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const rank = (p: LushaPerson) => {
    const at = targetsOf(p).map((k) => roles.indexOf(k)).filter((i) => i >= 0);
    return at.length ? Math.min(...at) : roles.length;
  };
  const shown = (data?.people ?? []).filter((p) => {
    if (hasPhone && !p.has_phone) return false;
    if (target && !targetsOf(p).includes(target)) return false;
    const hay = [p.name, p.title, p.seniority, ...(p.departments ?? [])].join(" ").toLowerCase();
    return terms.every((w) => hay.includes(w === "it" ? "information technology" : w) || hay.split(/[^a-z]+/).includes(w));
  }).sort((a, b) => rank(a) - rank(b) || Number(b.has_phone) - Number(a.has_phone)); // the product's buyers, with a phone, first
  const cost = pending?.kind === "reveal" ? (pending.field === "email" ? pending.person.email_credits : pending.person.phone_credits) : (data?.search_credits_estimate ?? 25);
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
      description={data?.searched_at ? `${data.people.length}${data.total && data.total > data.people.length ? ` of ${data.total}` : ""} people loaded · ${formatDate(data.searched_at)} · filtering is free, you pay only to reveal` : "Load the people Lusha has at this company once (paid), then filter them for free."}
      flush
    >
      {data?.searched_at ? (
        <form onSubmit={submit} className="flex flex-wrap items-center gap-3 px-4 py-3">
          <Select aria-label="Selling" value={product} onChange={(e) => { setProduct(e.target.value); setTarget(null); }} className="w-auto">
            {Object.entries(PRODUCTS).map(([key, p]) => (
              <option key={key} value={key}>
                Selling {p.label}
              </option>
            ))}
          </Select>
          <span className="flex flex-wrap gap-1.5" role="group" aria-label="Who do you need?">
            {roles.map((key) => (
              <Button key={key} type="button" size="sm" variant={target === key ? "primary" : "secondary"} aria-pressed={target === key} onClick={() => setTarget(target === key ? null : key)}>
                {ROLES[key].label}
              </Button>
            ))}
          </span>
          <SearchInput value={text} onChange={setText} label={`Filter Lusha people at ${companyName}`} placeholder="Filter: IT, manager, marketing, CFO…" className="min-w-[240px] flex-1" />
          <Checkbox label="Has phone" checked={hasPhone} onChange={(e) => setHasPhone(e.target.checked)} />
        </form>
      ) : (
        <div className="px-4 py-3">
          <Button size="sm" variant="secondary" onClick={() => void run(everyone)}>
            Load people from Lusha
          </Button>
        </div>
      )}
      {shown.length > 0 && (
        <DataTable
          caption="People from Lusha"
          rows={shown}
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
      {data?.searched_at && !shown.length && (
        <p className="px-4 pb-3 text-xs text-fg-subtle">{data.people.length ? `No one matches${terms.length ? ` “${text.trim()}”` : ""} in the loaded people.${data.has_more ? " Load more people below." : ""}` : "Lusha has no one at this company."}</p>
      )}
      {data?.has_more && query && (
        <div className="px-4 py-3">
          <Button size="sm" variant="ghost" onClick={() => void run({ ...query, page: query.page + 1 })}>
            Load more people (paid)
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={pending !== null}
        title={
          pending?.kind === "reveal"
            ? `Reveal ${pending.person.name}'s ${pending.field === "email" ? "work email" : "phone"}?`
            : pending && pending.query.page > 0
              ? `Load more of ${companyName}'s people from Lusha?`
              : `Load the people Lusha has at ${companyName}?`
        }
        confirmLabel={pending?.kind === "reveal" ? (pending.field === "phone" ? "Get number" : "Reveal email") : "Load people"}
        busy={busy}
        onConfirm={() => void confirm()}
        onClose={() => setPending(null)}
      >
        {cost === 0
          ? "Free: this was already revealed for TECOMSA's Lusha account."
          : pending?.kind === "reveal"
            ? `This uses about ${cost} Lusha credit${cost === 1 ? "" : "s"}${left(credits.data)}.${credits.data?.reveals_left_today != null ? ` You have ${credits.data.reveals_left_today} left today.` : ""} This can't be undone.`
            : `Lusha bills ${cost} credit${cost === 1 ? "" : "s"} for up to 25 people${left(credits.data)}. The list is kept, and filtering it is free: you pay again only to get a number.`}
      </ConfirmDialog>
    </Section>
  );
}
