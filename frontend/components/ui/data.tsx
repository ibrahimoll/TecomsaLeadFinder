"use client";

import clsx from "clsx";
import { AlertTriangle, ArrowDown, ChevronLeft, ChevronRight, X, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";

import { Button } from "./primitives";

// ---- Badge -----------------------------------------------------------------

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

const toneClass: Record<Tone, string> = {
  neutral: "bg-surface-muted text-fg-muted ring-border",
  accent: "bg-accent-soft text-accent ring-accent/20",
  success: "bg-success-soft text-success ring-success/20",
  warning: "bg-warning-soft text-warning ring-warning/25",
  danger: "bg-danger-soft text-danger ring-danger/20",
  info: "bg-info-soft text-info ring-info/20",
};
const dotClass: Record<Tone, string> = {
  neutral: "bg-fg-subtle",
  accent: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
};

/** `live` adds a pinging ring to the dot for work in progress. */
export function Badge({ tone = "neutral", dot, live, children }: { tone?: Tone; dot?: boolean; live?: boolean; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex h-5 items-center gap-1.5 whitespace-nowrap rounded-sm px-1.5 text-[11.5px] font-medium leading-none ring-1 ring-inset",
        toneClass[tone],
      )}
    >
      {dot && (
        <span className="relative flex h-1.5 w-1.5 shrink-0" aria-hidden>
          {live && <span className={clsx("absolute inset-0 animate-ping rounded-full opacity-70", dotClass[tone])} />}
          <span className={clsx("relative h-1.5 w-1.5 rounded-full", dotClass[tone])} />
        </span>
      )}
      {children}
    </span>
  );
}

// ---- Loading / empty / error ---------------------------------------------

export function Skeleton({ className }: { className?: string }) {
  return <span className={clsx("skeleton-shimmer block rounded-sm", className)} aria-hidden />;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  compact,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={clsx("flex animate-page-in flex-col items-center justify-center px-6 text-center", compact ? "py-7" : "py-14")}>
      {icon && (
        <div
          className={clsx(
            "flex items-center justify-center rounded-lg bg-surface-muted text-fg-muted ring-1 ring-inset ring-border [&_svg]:h-[18px] [&_svg]:w-[18px]",
            compact ? "mb-2.5 h-9 w-9" : "mb-3 h-10 w-10",
          )}
        >
          {icon}
        </div>
      )}
      <p className="font-display text-[14px] font-semibold text-fg">{title}</p>
      {description && <p className="mt-1 max-w-sm text-[13px] text-fg-muted">{description}</p>}
      {action && <div className="mt-4 flex gap-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex animate-page-in flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-danger-soft text-danger ring-1 ring-inset ring-danger/20">
        <AlertTriangle className="h-[18px] w-[18px]" aria-hidden />
      </div>
      <p className="font-display text-[14px] font-semibold text-fg">Could not load this data</p>
      <p className="mt-1 max-w-md text-[13px] text-fg-muted">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Alert({
  tone = "danger",
  title,
  children,
}: {
  tone?: Exclude<Tone, "neutral" | "accent">;
  title?: string;
  children?: ReactNode;
}) {
  const styles = {
    danger: "border-danger/20 bg-danger-soft/70 [&_.alert-title]:text-danger",
    warning: "border-warning/25 bg-warning-soft/70 [&_.alert-title]:text-warning",
    success: "border-success/20 bg-success-soft/70 [&_.alert-title]:text-success",
    info: "border-info/20 bg-info-soft/70 [&_.alert-title]:text-info",
  }[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={clsx("animate-page-in rounded border px-3 py-2 text-[13px]", styles)}>
      {title && <p className="alert-title font-medium">{title}</p>}
      {children && <div className={clsx(title && "mt-0.5", "text-fg")}>{children}</div>}
    </div>
  );
}

// ---- Data table ------------------------------------------------------------

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  sortKey?: string;
  align?: "left" | "right";
  className?: string;
}

export interface Selection<K> {
  selected: Set<K>;
  onChange: (next: Set<K>) => void;
}

function IndeterminateCheckbox({
  checked,
  indeterminate,
  onChange,
  label,
}: {
  checked: boolean;
  indeterminate?: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = Boolean(indeterminate);
  }, [indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      aria-label={label}
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
      className="m-0 block h-3.5 w-3.5 cursor-pointer rounded-sm accent-[rgb(var(--accent))]"
    />
  );
}

const INTERACTIVE = "a, button, input, select, textarea, label, [role='button']";

/**
 * Dense, scannable table: sticky header, 36px rows, optional row selection and
 * whole-row navigation (`rowHref`) that never hijacks links or buttons inside a row.
 */
export function DataTable<T, K extends string | number = string | number>({
  columns,
  rows,
  rowKey,
  loading,
  error,
  onRetry,
  empty,
  sort,
  onSort,
  caption,
  selection,
  rowHref,
}: {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => K;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  empty?: ReactNode;
  sort?: string;
  onSort?: (key: string) => void;
  caption?: string;
  selection?: Selection<K>;
  /** Whole-row link; return null for rows that should not navigate. */
  rowHref?: (row: T) => string | null;
}) {
  const router = useRouter();
  // Live data: when a refetch/poll changes a row that was already on screen, flash it briefly.
  // Never on first load or page change (those rows are new, not changed).
  const previous = useRef<Map<K, string>>(new Map());
  const [flashing, setFlashing] = useState<Set<K>>(() => new Set());
  useEffect(() => {
    if (!rows) return;
    const next = new Map<K, string>();
    const changed = new Set<K>();
    for (const row of rows) {
      const key = rowKey(row);
      const signature = JSON.stringify(row);
      next.set(key, signature);
      const before = previous.current.get(key);
      if (before !== undefined && before !== signature) changed.add(key);
    }
    previous.current = next;
    if (!changed.size) return;
    setFlashing(changed);
    const timer = setTimeout(() => setFlashing(new Set()), 1600);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rowKey is a stable selector in practice
  }, [rows]);
  if (error) return <ErrorState message={error} onRetry={onRetry} />;
  // No rows yet = loading, even before the request has flagged it (e.g. the first render after a tab
  // switch). Rendering `rows` while undefined used to crash the page.
  const showSkeleton = !rows;
  const refreshing = Boolean(loading && rows);
  if (!showSkeleton && rows && rows.length === 0) return <>{empty ?? <EmptyState title="Nothing here yet" />}</>;

  const keys = rows?.map(rowKey) ?? [];
  const selectedHere = selection ? keys.filter((k) => selection.selected.has(k)).length : 0;
  const cell = "border-b border-border px-3 first:pl-4 last:pr-4";

  function toggleAll(checked: boolean) {
    if (!selection) return;
    const next = new Set(selection.selected);
    keys.forEach((k) => (checked ? next.add(k) : next.delete(k)));
    selection.onChange(next);
  }
  function toggle(key: K, checked: boolean) {
    if (!selection) return;
    const next = new Set(selection.selected);
    if (checked) next.add(key);
    else next.delete(key);
    selection.onChange(next);
  }
  function onRowClick(event: MouseEvent, row: T) {
    if (!rowHref || (event.target as HTMLElement).closest(INTERACTIVE)) return;
    if (window.getSelection()?.toString()) return; // the user is selecting text
    const href = rowHref(row);
    if (!href) return;
    if (event.metaKey || event.ctrlKey) window.open(href, "_blank");
    else router.push(href);
  }

  return (
    <div className="relative overflow-x-auto" aria-busy={refreshing || undefined}>
      {refreshing && (
        <span className="pointer-events-none absolute inset-x-0 top-0 z-[3] block h-0.5 overflow-hidden bg-accent-soft" aria-hidden>
          <span className="absolute inset-y-0 left-0 w-1/3 animate-[loading-bar_1.1s_ease-in-out_infinite] bg-accent" />
        </span>
      )}
      <table className={clsx("min-w-full border-separate border-spacing-0 text-[13px] transition-opacity duration-200", refreshing && "opacity-60")}>
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {selection && (
              <th scope="col" className="sticky top-0 z-[2] h-8 w-9 border-b border-border bg-surface-muted/95 pl-4 pr-0 align-middle backdrop-blur">
                <IndeterminateCheckbox
                  label="Select all rows"
                  checked={keys.length > 0 && selectedHere === keys.length}
                  indeterminate={selectedHere > 0 && selectedHere < keys.length}
                  onChange={toggleAll}
                />
              </th>
            )}
            {columns.map((col) => {
              const active = sort && col.sortKey && sort === col.sortKey;
              return (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={active ? "descending" : undefined}
                  className={clsx(
                    "sticky top-0 z-[1] h-8 whitespace-nowrap border-b border-border bg-surface-muted/95 px-3 text-left text-[11.5px] font-medium text-fg-muted backdrop-blur first:pl-4 last:pr-4",
                    selection && "[&:nth-child(2)]:pl-2",
                    col.align === "right" && "text-right",
                  )}
                >
                  {col.sortKey && onSort ? (
                    <button
                      type="button"
                      onClick={() => onSort(col.sortKey!)}
                      className={clsx("group/sort inline-flex items-center gap-1 hover:text-fg", active && "text-fg")}
                    >
                      {col.header}
                      <ArrowDown
                        className={clsx("h-3 w-3 transition-opacity", active ? "opacity-100" : "opacity-0 group-hover/sort:opacity-40")}
                        aria-hidden
                      />
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody key={showSkeleton ? "skeleton" : "rows"} className={showSkeleton ? undefined : "animate-content-in"}>
          {showSkeleton
            ? Array.from({ length: 8 }, (_, i) => (
                <tr key={i}>
                  {selection && <td className={clsx(cell, "h-9 w-9")} />}
                  {columns.map((col, c) => (
                    <td key={col.key} className={clsx(cell, "h-9")}>
                      <Skeleton className={clsx("h-3", c === 0 ? "w-40" : "w-20")} />
                    </td>
                  ))}
                </tr>
              ))
            : rows!.map((row) => {
                const key = rowKey(row);
                const isSelected = selection?.selected.has(key) ?? false;
                return (
                  <tr
                    key={key}
                    onClick={rowHref ? (e) => onRowClick(e, row) : undefined}
                    aria-selected={selection ? isSelected : undefined}
                    className={clsx(
                      "group transition-colors duration-150",
                      flashing.has(key) && "animate-row-flash",
                      isSelected ? "bg-accent-soft/60" : "hover:bg-surface-hover/70",
                      rowHref?.(row) && "cursor-pointer",
                    )}
                  >
                    {selection && (
                      <td className={clsx(cell, "h-9 w-9 pr-0 align-middle")}>
                        <IndeterminateCheckbox label="Select row" checked={isSelected} onChange={(c) => toggle(key, c)} />
                      </td>
                    )}
                    {columns.map((col) => (
                      <td
                        key={col.key}
                        className={clsx(
                          cell,
                          "h-9 whitespace-nowrap align-middle text-fg",
                          selection && "[&:nth-child(2)]:pl-2",
                          col.align === "right" && "text-right tabular",
                          col.className,
                        )}
                      >
                        {col.cell(row)}
                      </td>
                    ))}
                  </tr>
                );
              })}
        </tbody>
      </table>
    </div>
  );
}

/** Floating bulk-action bar shown while table rows are selected (Linear-style). */
export function SelectionBar({ count, onClear, children }: { count: number; onClear: () => void; children: ReactNode }) {
  if (count === 0) return null;
  return (
    <div className="fixed inset-x-0 bottom-5 z-30 flex justify-center px-4" role="region" aria-label="Bulk actions">
      <div className="elevated flex animate-slide-up items-center gap-1 rounded-lg bg-ink py-1 pl-3 pr-1 text-[13px] text-white">
        <span className="mr-2 tabular font-medium">{count} selected</span>
        <span className="mr-1 h-4 w-px bg-white/15" aria-hidden />
        <div className="flex items-center gap-1 [&_button]:text-white/85 [&_button:hover]:bg-white/10 [&_button:hover]:text-white [&_a]:text-white/85 [&_a:hover]:bg-white/10">
          {children}
        </div>
        <button
          type="button"
          onClick={onClear}
          aria-label="Clear selection"
          className="ml-1 rounded p-1.5 text-white/60 hover:bg-white/10 hover:text-white"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

export function RowLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="font-medium text-fg decoration-fg-subtle underline-offset-2 hover:underline">
      {children}
    </Link>
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  if (total === 0) return null;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <nav aria-label="Pagination" className="flex h-10 items-center justify-between px-4 text-xs text-fg-muted">
      <span className="tabular">
        <span className="text-fg">
          {from.toLocaleString()}–{to.toLocaleString()}
        </span>{" "}
        of {total.toLocaleString()}
      </span>
      {pages > 1 && (
        <div className="flex items-center gap-1">
          <Button variant="secondary" size="icon" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
            <ChevronLeft className="h-3.5 w-3.5" />
          </Button>
          <span className="tabular px-1.5">
            Page {page} of {pages}
          </span>
          <Button variant="secondary" size="icon" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </nav>
  );
}

// ---- Metrics / lists ---------------------------------------------------------

/** "12 / 50" with a short bar: progress toward a target, green once reached. */
export function Meter({ value, max, className }: { value: number; max: number; className?: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <span className={clsx("inline-flex items-center gap-2 tabular", className)} title={`${value} of ${max}`}>
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-surface-muted" aria-hidden>
        <span className={clsx("block h-full origin-left animate-grow-x rounded-full", pct >= 100 ? "bg-success" : "bg-accent")} style={{ width: `${Math.max(pct, value ? 4 : 0)}%` }} />
      </span>
      <span>
        <span className="font-medium text-fg">{value}</span>
        <span className="text-fg-subtle"> / {max}</span>
      </span>
    </span>
  );
}

export interface Metric {
  label: string;
  value: number | string;
  href?: string;
  hint?: string;
  icon?: LucideIcon;
  /** Small chip beside the hint, e.g. a share of the total (pattern adapted from 21st.dev "Statistics Card 10"). */
  badge?: { label: string; tone?: Tone };
}

/**
 * Shows `value` immediately, then animates from the old to the new value when it changes
 * (pattern from 21st.dev "Number Ticker"). Instant when the user prefers reduced motion.
 */
/**
 * "12 min ago", kept current (re-renders every 30s); the exact date and time are in the tooltip.
 * Live data: a salesperson sees at a glance how fresh a search or import is.
 */
export function TimeAgo({ value }: { value: string | null | undefined }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);
  if (!value) return <span className="text-fg-subtle">—</span>;
  const date = new Date(value);
  const s = Math.max(0, Math.round((now - date.getTime()) / 1000));
  const label =
    s < 45 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : s < 7 * 86400 ? `${Math.round(s / 86400)} d ago` : date.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
  return (
    <time dateTime={value} title={date.toLocaleString()} className="whitespace-nowrap">
      {label}
    </time>
  );
}

/** Numbers already revealed in this browser session (path + key), so they do not recount on every visit. */
const revealed = new Set<string>();

export function CountUp({ value, duration = 600, reveal }: { value: number; duration?: number; reveal?: string }) {
  // `reveal`: count up from 0 the first time this number is shown in the session.
  // Pure check here (React may call initialisers twice); the visit is recorded in the effect below.
  const [shown, setShown] = useState(() =>
    reveal && typeof window !== "undefined" && !revealed.has(`${window.location.pathname}|${reveal}`) ? 0 : value,
  );
  useEffect(() => {
    if (reveal) revealed.add(`${window.location.pathname}|${reveal}`);
  }, [reveal]);
  // Track what is actually on screen. The animation restarts from there, so it survives React re-running
  // the effect (Strict Mode in development) and value changes mid-animation.
  const onScreen = useRef(shown);
  useEffect(() => {
    if (onScreen.current === value) return;
    const show = (n: number) => {
      onScreen.current = n;
      setShown(n);
    };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      show(value);
      return;
    }
    const origin = onScreen.current;
    const span = origin === 0 && reveal ? Math.max(duration, 900) : duration;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / span);
      show(Math.round(origin + (value - origin) * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration, reveal]);
  return <>{shown.toLocaleString()}</>;
}

/** KPI cards: label + icon tile, a large figure, an optional chip and hint. */
export function MetricStrip({ items, loading }: { items: Metric[]; loading?: boolean }) {
  return (
    <dl className="stagger grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-flow-col lg:auto-cols-fr lg:grid-cols-none">
      {items.map((item) => {
        const Icon = item.icon;
        const body = (
          <>
            <div className="flex items-start justify-between gap-2">
              <dt className="text-[12.5px] font-medium text-fg-muted">{item.label}</dt>
              {Icon && <Icon className="h-4 w-4 shrink-0 text-fg-subtle" strokeWidth={1.75} aria-hidden />}
            </div>
            <dd className="mt-2 font-display text-[26px] font-semibold leading-8 tracking-[-0.02em] tabular text-fg">
              {loading ? <Skeleton className="h-7 w-16" /> : typeof item.value === "number" ? <CountUp value={item.value} reveal={`metric:${item.label}`} /> : item.value}
            </dd>
            {(item.badge || item.hint) && (
              <dd className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-fg-subtle">
                {item.badge && !loading && <Badge tone={item.badge.tone}>{item.badge.label}</Badge>}
                {item.hint}
              </dd>
            )}
          </>
        );
        const cls = "block rounded-lg border border-border bg-surface p-4 shadow-xs";
        return item.href ? (
          <Link
            key={item.label}
            href={item.href}
            className={clsx(cls, "transition-[border-color,box-shadow] duration-150 hover:border-border-strong hover:shadow-card-hover")}
          >
            {body}
          </Link>
        ) : (
          <div key={item.label} className={cls}>
            {body}
          </div>
        );
      })}
    </dl>
  );
}

export function DescriptionList({
  items,
  columns = 2,
  inline,
}: {
  items: { label: string; value: ReactNode; icon?: ReactNode }[];
  columns?: 1 | 2 | 3;
  /** Record layout: label and value side by side on one aligned row (pattern adapted from 21st.dev "Key Value List"). */
  inline?: boolean;
}) {
  if (inline) {
    return (
      <dl className={clsx("grid gap-x-10", columns > 1 && "md:grid-cols-2")}>
        {items.map((item) => (
          <div key={item.label} className="group grid min-h-[34px] min-w-0 grid-cols-[9rem_minmax(0,1fr)] items-center gap-x-4 border-b border-border/70 text-[13px]">
            <dt className="flex items-center gap-2 text-fg-muted [&_svg]:h-3.5 [&_svg]:w-3.5 [&_svg]:text-fg-subtle">
              {item.icon}
              {item.label}
            </dt>
            <dd className="flex min-w-0 items-center gap-1 break-words py-1.5 text-fg">{item.value}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <dl
      className={clsx(
        "grid gap-x-8 gap-y-3",
        columns === 1 && "grid-cols-1",
        columns === 2 && "grid-cols-1 sm:grid-cols-2",
        columns === 3 && "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
      )}
    >
      {items.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-xs text-fg-muted">{item.label}</dt>
          <dd className="mt-0.5 break-words text-[13px] text-fg">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Deterministic, muted initials tile (one of six neutral-leaning hues per name). */
const AVATAR_HUES = [
  "bg-[#EEF1EC] text-[#46533F]",
  "bg-[#ECEFF4] text-[#3E4B63]",
  "bg-[#F3EEEA] text-[#65493A]",
  "bg-[#EDF1F1] text-[#35585A]",
  "bg-[#F1EEF3] text-[#553F63]",
  "bg-[#F2F0E8] text-[#5E5530]",
];

/**
 * Initials avatar. With `domain`, shows the company's site icon (via DuckDuckGo's icon service,
 * which receives only the domain) and falls back to initials if there is none.
 */
export function Avatar({ name, size = "md", domain }: { name: string; size?: "sm" | "md" | "lg" | "xl"; domain?: string | null }) {
  const [logoFailed, setLogoFailed] = useState(false);
  const initials =
    name
      .replace(/[^\p{L}\p{N}\s]/gu, " ")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]!.toUpperCase())
      .join("") || "?";
  const hue = AVATAR_HUES[[...name].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % AVATAR_HUES.length];
  return (
    <span
      aria-hidden
      className={clsx(
        "inline-flex shrink-0 items-center justify-center rounded font-semibold ring-1 ring-inset ring-black/[0.04]",
        hue,
        size === "sm" && "h-6 w-6 text-[10px]",
        size === "md" && "h-7 w-7 text-[11px]",
        size === "lg" && "h-10 w-10 text-sm",
        size === "xl" && "h-14 w-14 rounded-xl text-lg",
        domain && !logoFailed && "bg-surface",
      )}
    >
      {domain && !logoFailed ? (
        // eslint-disable-next-line @next/next/no-img-element -- tiny third-party icon, no optimisation needed
        <img
          src={`https://icons.duckduckgo.com/ip3/${encodeURIComponent(domain)}.ico`}
          alt=""
          loading="lazy"
          className="h-[70%] w-[70%] animate-[fade-in_200ms_ease-out] object-contain"
          onError={() => setLogoFailed(true)}
          // DuckDuckGo answers an unknown domain with its 48x48 grey-arrow placeholder (an image, though a 404):
          // ponytail: a real 48x48 favicon shows initials too
          onLoad={(e) => e.currentTarget.naturalWidth === 48 && e.currentTarget.naturalHeight === 48 && setLogoFailed(true)}
        />
      ) : (
        initials
      )}
    </span>
  );
}
