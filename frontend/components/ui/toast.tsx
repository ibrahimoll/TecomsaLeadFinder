"use client";

import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";

/**
 * App-wide toasts for outcomes that otherwise happen silently (claim, note added, status changed…).
 * A tiny module store, so a toast raised just before navigating still shows on the next page.
 * Inline Alerts stay the place for errors that need the user's attention in context.
 */
type Tone = "success" | "error" | "info";
interface ToastItem {
  id: number;
  tone: Tone;
  title: string;
  description?: string;
}

let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

function push(tone: Tone, title: string, description?: string) {
  items = [...items.slice(-3), { id: nextId++, tone, title, description }];
  emit();
}

export function dismissToast(id: number) {
  items = items.filter((t) => t.id !== id);
  emit();
}

export const toast = {
  success: (title: string, description?: string) => push("success", title, description),
  error: (title: string, description?: string) => push("error", title, description),
  info: (title: string, description?: string) => push("info", title, description),
};

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const snapshot = () => items;
const empty: ToastItem[] = [];

const ICON = { success: CheckCircle2, error: AlertTriangle, info: Info };
const ICON_TONE = { success: "text-success", error: "text-danger", info: "text-info" };
const BAR = { success: "bg-success", error: "bg-danger", info: "bg-info" };
const DURATION = { success: 3500, info: 4000, error: 6500 };

function ToastCard({ t }: { t: ToastItem }) {
  useEffect(() => {
    const timer = setTimeout(() => dismissToast(t.id), DURATION[t.tone]);
    return () => clearTimeout(timer);
  }, [t.id, t.tone]);
  const Icon = ICON[t.tone];
  return (
    <div
      role={t.tone === "error" ? "alert" : "status"}
      className="elevated pointer-events-auto relative flex w-[min(360px,calc(100vw-2rem))] animate-toast-in items-start gap-3 overflow-hidden rounded-lg bg-surface px-4 py-3"
    >
      <Icon className={clsx("mt-0.5 h-4 w-4 shrink-0", ICON_TONE[t.tone])} aria-hidden />
      <div className="min-w-0 flex-1 text-[13px]">
        <p className="font-medium text-fg">{t.title}</p>
        {t.description && <p className="mt-0.5 text-fg-muted">{t.description}</p>}
      </div>
      <button
        type="button"
        onClick={() => dismissToast(t.id)}
        aria-label="Dismiss"
        className="-mr-1 rounded p-1 text-fg-subtle transition-colors hover:bg-surface-hover hover:text-fg"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
      {/* Time left before it closes. */}
      <span
        className={clsx("absolute bottom-0 left-0 h-0.5 w-full origin-left opacity-60", BAR[t.tone])}
        style={{ animation: `toast-timer ${DURATION[t.tone]}ms linear forwards` }}
        aria-hidden
      />
    </div>
  );
}

/** Mounted once in the app shell. */
export function Toaster() {
  const list = useSyncExternalStore(subscribe, snapshot, () => empty);
  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex flex-col items-end gap-2" aria-live="polite">
      {list.map((t) => (
        <ToastCard key={t.id} t={t} />
      ))}
    </div>
  );
}
