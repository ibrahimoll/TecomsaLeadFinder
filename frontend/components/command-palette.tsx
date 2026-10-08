"use client";

import clsx from "clsx";
import { Building2, CornerDownLeft, Loader2, Search, type LucideIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { CrmStatusBadge } from "@/components/status-badges";
import { Avatar, Kbd } from "@/components/ui";
import { api } from "@/lib/api";
import { recentCompanies, type RecentCompany } from "@/lib/recent";
import type { Company, Page } from "@/types";

export interface PaletteCommand {
  id: string;
  label: string;
  group: "Go to" | "Actions";
  href: string;
  icon: LucideIcon;
  keywords?: string;
}

type Item =
  | (PaletteCommand & { kind: "command" })
  | { kind: "company"; id: string; href: string; company: Company | RecentCompany; recent?: boolean };

/**
 * ⌘K command palette (pattern adapted from 21st.dev's Raycast-style "Command Palette"):
 * jump to pages, run actions, or search companies. Arrow keys + Enter, Esc to close.
 */
export function CommandPalette({
  open,
  onClose,
  commands,
}: {
  open: boolean;
  onClose: () => void;
  commands: PaletteCommand[];
}) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [searching, setSearching] = useState(false);
  const [recent, setRecent] = useState<RecentCompany[]>([]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    setCompanies([]);
    setRecent(recentCompanies());
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  // Live company search (debounced) once the query is meaningful.
  useEffect(() => {
    const q = query.trim();
    if (!open || q.length < 2) {
      setCompanies([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    const t = setTimeout(() => {
      api<Page<Company>>("/companies", { query: { q, page_size: 6 } })
        .then((r) => setCompanies(r.items))
        .catch(() => setCompanies([]))
        .finally(() => setSearching(false));
    }, 180);
    return () => clearTimeout(t);
  }, [query, open]);

  const items: Item[] = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched = commands
      .filter((c) => !q || `${c.label} ${c.keywords ?? ""}`.toLowerCase().includes(q))
      .map((c) => ({ ...c, kind: "command" as const }));
    const found = companies.map((company) => ({
      kind: "company" as const,
      id: `company-${company.id}`,
      href: `/companies/${company.id}`,
      company,
    }));
    const recents = q
      ? []
      : recent.map((company) => ({ kind: "company" as const, id: `recent-${company.id}`, href: `/companies/${company.id}`, company, recent: true }));
    return [...recents, ...found, ...matched];
  }, [commands, companies, query, recent]);

  useEffect(() => setActive(0), [items.length]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  function go(item: Item | undefined) {
    if (!item) return;
    onClose();
    router.push(item.href);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(items[active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  }

  const groups: { title: string; items: { item: Item; index: number }[] }[] = [];
  items.forEach((item, index) => {
    const title = item.kind === "company" ? (item.recent ? "Recently viewed" : "Companies") : item.group;
    const group = groups.find((g) => g.title === title) ?? groups[groups.push({ title, items: [] }) - 1]!;
    group.items.push({ item, index });
  });

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[14vh]" role="dialog" aria-modal="true" aria-label="Command menu">
      <button className="absolute inset-0 animate-[fade-in_120ms_ease-out] bg-ink/30 backdrop-blur-[2px]" aria-label="Close command menu" onClick={onClose} tabIndex={-1} />
      <div className="elevated relative w-full max-w-[560px] animate-pop-in overflow-hidden rounded-lg bg-surface" onKeyDown={onKeyDown}>
        <div className="flex items-center gap-2.5 border-b border-border px-4">
          {searching ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-fg-subtle" aria-hidden />
          ) : (
            <Search className="h-4 w-4 shrink-0 text-fg-subtle" aria-hidden />
          )}
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search companies, pages and actions…"
            className="h-12 flex-1 bg-transparent text-[14px] text-fg placeholder:text-fg-subtle focus:outline-none"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={items[active] ? `palette-${items[active]!.id}` : undefined}
          />
          <Kbd>Esc</Kbd>
        </div>
        <div ref={listRef} id="palette-list" role="listbox" className="max-h-[360px] overflow-y-auto p-1.5">
          {items.length === 0 ? (
            <p className="px-3 py-8 text-center text-[13px] text-fg-muted">
              {searching ? "Searching…" : `No results for “${query}”`}
            </p>
          ) : (
            groups.map((group) => (
              <div key={group.title} className="mb-1 last:mb-0">
                <p className="px-2.5 pb-1 pt-2 text-[11px] font-medium text-fg-subtle">{group.title}</p>
                {group.items.map(({ item, index }) => {
                  const Icon = item.kind === "company" ? Building2 : item.icon;
                  const selected = index === active;
                  return (
                    <div
                      key={item.id}
                      id={`palette-${item.id}`}
                      data-index={index}
                      role="option"
                      aria-selected={selected}
                      onMouseMove={() => setActive(index)}
                      onClick={() => go(item)}
                      className={clsx(
                        "relative flex h-9 cursor-pointer items-center gap-2.5 rounded px-2.5 text-[13px] transition-colors duration-100",
                        selected ? "bg-accent-soft/70 text-fg before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-full before:bg-accent" : "text-fg-muted",
                      )}
                    >
                      {item.kind === "company" ? (
                        <Avatar name={item.company.name} size="sm" domain={item.company.domain} />
                      ) : (
                        <Icon className={clsx("h-4 w-4 shrink-0", selected ? "text-accent" : "text-fg-subtle")} aria-hidden />
                      )}
                      {item.kind === "company" ? (
                        <>
                          <span className="min-w-0 flex-1 truncate font-medium text-fg">{item.company.name}</span>
                          <span className="hidden truncate text-xs text-fg-subtle sm:inline">
                            {[item.company.city, item.company.country].filter(Boolean).join(", ")}
                          </span>
                          <CrmStatusBadge status={item.company.odoo_status} />
                        </>
                      ) : (
                        <span className="flex-1 truncate">{item.label}</span>
                      )}
                      {selected && <CornerDownLeft className="h-3.5 w-3.5 shrink-0 animate-pop-in text-accent" aria-hidden />}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>
        <div className="flex items-center gap-3 border-t border-border bg-surface-muted/50 px-3.5 py-2 text-[11px] text-fg-subtle">
          <span className="flex items-center gap-1">
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd> navigate
          </span>
          <span className="flex items-center gap-1">
            <Kbd>↵</Kbd> open
          </span>
          <span className="ml-auto flex items-center gap-1">
            Type 2+ letters to search companies · <Kbd>?</Kbd> shortcuts
          </span>
        </div>
      </div>
    </div>
  );
}
