"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Kbd } from "@/components/ui";

/** `g` then a letter jumps to a page (Linear/GitHub style). */
const GO: Record<string, { href: string; label: string }> = {
  d: { href: "/dashboard", label: "Dashboard" },
  f: { href: "/discovery", label: "Find companies" },
  c: { href: "/companies", label: "Companies" },
  l: { href: "/leads", label: "Qualified leads" },
  p: { href: "/campaigns", label: "Campaigns" },
  a: { href: "/activity", label: "My activity" },
};

function typing(target: EventTarget | null) {
  const el = target as HTMLElement | null;
  return Boolean(el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)));
}

/**
 * Global keyboard shortcuts. Never fires while the user is typing in a field.
 *   /        focus the page's search box (or open the command menu if the page has none)
 *   g + key  go to a page
 *   ?        show this list
 */
export function KeyboardShortcuts({ onOpenPalette }: { onOpenPalette: () => void }) {
  const router = useRouter();
  const [help, setHelp] = useState(false);
  const pendingG = useRef<number | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      if (pendingG.current !== null) {
        window.clearTimeout(pendingG.current);
        pendingG.current = null;
        const dest = GO[e.key.toLowerCase()];
        if (dest) {
          e.preventDefault();
          router.push(dest.href);
        }
        return;
      }
      if (e.key === "g") {
        pendingG.current = window.setTimeout(() => (pendingG.current = null), 1000);
      } else if (e.key === "/") {
        e.preventDefault();
        const search = document.querySelector<HTMLInputElement>("main input[type=search]");
        if (search) search.focus();
        else onOpenPalette();
      } else if (e.key === "?") {
        e.preventDefault();
        setHelp(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, onOpenPalette]);

  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    if (help && !d.open) d.showModal();
    if (!help && d.open) d.close();
  }, [help]);

  const rows: [string[], string][] = [
    [["Ctrl", "K"], "Search companies, pages and actions"],
    [["/"], "Focus the search on this page"],
    ...Object.entries(GO).map(([k, v]) => [["g", k], `Go to ${v.label}`] as [string[], string]),
    [["?"], "Show these shortcuts"],
  ];

  return (
    <dialog
      ref={dialog}
      onClose={() => setHelp(false)}
      aria-labelledby="shortcuts-title"
      className="elevated w-[min(420px,calc(100vw-2rem))] rounded-lg border-0 bg-surface p-0 text-fg"
    >
      <div className="border-b border-border px-5 py-4">
        <h2 id="shortcuts-title" className="text-[15px] font-semibold">
          Keyboard shortcuts
        </h2>
        <p className="mt-0.5 text-xs text-fg-muted">They work anywhere except while typing in a field.</p>
      </div>
      <ul className="divide-y divide-border px-5 py-1.5 text-[13px]">
        {rows.map(([keys, label]) => (
          <li key={label} className="flex items-center justify-between gap-4 py-2">
            <span className="text-fg-muted">{label}</span>
            <span className="flex shrink-0 items-center gap-1">
              {keys.map((k, i) => (
                <span key={i} className="flex items-center gap-1">
                  {i > 0 && keys[0] === "g" && <span className="text-[11px] text-fg-subtle">then</span>}
                  <Kbd>{k}</Kbd>
                </span>
              ))}
            </span>
          </li>
        ))}
      </ul>
      <div className="flex justify-end border-t border-border bg-surface-muted/50 px-5 py-3">
        <button
          type="button"
          onClick={() => setHelp(false)}
          className="h-8 rounded border border-border-strong bg-surface px-3 text-[12.5px] font-medium shadow-xs transition-colors hover:bg-surface-hover"
        >
          Close
        </button>
      </div>
    </dialog>
  );
}
