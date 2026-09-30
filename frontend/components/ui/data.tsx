"use client";

import clsx from "clsx";
import { AlertTriangle, ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

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

export function Badge({ tone = "neutral", dot, children }: { tone?: Tone; dot?: boolean; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex h-5 items-center gap-1.5 whitespace-nowrap rounded-sm px-1.5 text-xs font-medium ring-1 ring-inset",
        toneClass[tone],
      )}
    >
      {dot && <span className={clsx("h-1.5 w-1.5 rounded-full", dotClass[tone])} aria-hidden />}
      {children}
    </span>
  );
}

// ---- Loading / empty / error ---------------------------------------------

export function Skeleton({ className }: { className?: string }) {
  return <span className={clsx("block animate-pulse rounded-sm bg-surface-muted", className)} aria-hidden />;
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
    <div className={clsx("flex flex-col items-center justify-center px-6 text-center", compact ? "py-6" : "py-12")}>
      {icon && <div className="mb-2 text-fg-subtle">{icon}</div>}
      <p className="text-[13px] font-medium text-fg">{title}</p>
      {description && <p className="mt-1 max-w-md text-[13px] text-fg-muted">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center px-6 py-10 text-center">
      <AlertTriangle className="mb-2 h-5 w-5 text-danger" aria-hidden />
      <p className="text-[13px] font-medium text-fg">Could not load this data</p>
      <p className="mt-1 max-w-md text-[13px] text-fg-muted">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
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
    danger: "border-danger/25 bg-danger-soft text-danger",
    warning: "border-warning/30 bg-warning-soft text-warning",
    success: "border-success/25 bg-success-soft text-success",
    info: "border-info/25 bg-info-soft text-info",
  }[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={clsx("rounded border px-3 py-2 text-[13px]", styles)}>
      {title && <p className="font-medium">{title}</p>}
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

export function DataTable<T>({
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
}: {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => string | number;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  empty?: ReactNode;
  sort?: string;
  onSort?: (key: string) => void;
  caption?: string;
}) {
  if (error) return <ErrorState message={error} onRetry={onRetry} />;
  const showSkeleton = loading && !rows;
  if (!showSkeleton && rows && rows.length === 0) return <>{empty ?? <EmptyState title="Nothing here yet" />}</>;

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-separate border-spacing-0 text-[13px]">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((col) => {
              const active = sort && col.sortKey && sort === col.sortKey;
              return (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={active ? "other" : undefined}
                  className={clsx(
                    "sticky top-0 z-[1] h-8 whitespace-nowrap border-b border-border bg-surface-muted px-3 text-left text-xs font-medium text-fg-muted first:pl-4 last:pr-4",
                    col.align === "right" && "text-right",
                  )}
                >
                  {col.sortKey && onSort ? (
                    <button
                      type="button"
                      onClick={() => onSort(col.sortKey!)}
                      className="inline-flex items-center gap-1 hover:text-fg"
                    >
                      {col.header}
                      {active ? <ArrowDown className="h-3 w-3" aria-hidden /> : <ArrowUp className="h-3 w-3 opacity-0" aria-hidden />}
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {showSkeleton
            ? Array.from({ length: 6 }, (_, i) => (
                <tr key={i}>
                  {columns.map((col) => (
                    <td key={col.key} className="h-10 border-b border-border px-3 first:pl-4 last:pr-4">
                      <Skeleton className="h-3 w-3/4" />
                    </td>
                  ))}
                </tr>
              ))
            : rows!.map((row) => (
                <tr key={rowKey(row)} className="group hover:bg-surface-hover/60">
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={clsx(
                        "h-10 whitespace-nowrap border-b border-border px-3 align-middle text-fg first:pl-4 last:pr-4",
                        col.align === "right" && "text-right tabular",
                        col.className,
                      )}
                    >
                      {col.cell(row)}
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );
}

export function RowLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="font-medium text-fg hover:text-accent hover:underline">
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
    <nav aria-label="Pagination" className="flex items-center justify-between px-4 py-2 text-xs text-fg-muted">
      <span className="tabular">
        {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
      </span>
      {pages > 1 && (
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
            <ChevronLeft className="h-3.5 w-3.5" />
          </Button>
          <span className="tabular px-1">
            {page} / {pages}
          </span>
          <Button variant="ghost" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </nav>
  );
}

// ---- Metrics / lists ---------------------------------------------------------

export interface Metric {
  label: string;
  value: number | string;
  href?: string;
  hint?: string;
}

/** A single compact strip of figures, divided by rules rather than separate cards. */
export function MetricStrip({ items, loading }: { items: Metric[]; loading?: boolean }) {
  return (
    <dl className="grid grid-cols-2 overflow-hidden rounded-lg border border-border bg-surface sm:grid-cols-3 lg:grid-flow-col lg:auto-cols-fr lg:grid-cols-none">
      {items.map((item) => {
        const body = (
          <>
            <dt className="text-xs text-fg-muted">{item.label}</dt>
            <dd className="mt-1 text-xl font-semibold tabular text-fg">
              {loading ? <Skeleton className="h-6 w-12" /> : typeof item.value === "number" ? item.value.toLocaleString() : item.value}
            </dd>
            {item.hint && <dd className="mt-0.5 text-2xs text-fg-subtle">{item.hint}</dd>}
          </>
        );
        const cls = "block border-b border-r border-border px-4 py-3 -mb-px -mr-px";
        return item.href ? (
          <Link key={item.label} href={item.href} className={clsx(cls, "hover:bg-surface-hover/60")}>
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

export function DescriptionList({ items, columns = 2 }: { items: { label: string; value: ReactNode }[]; columns?: 1 | 2 | 3 }) {
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

export function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  const initials =
    name
      .replace(/[^\p{L}\p{N}\s]/gu, " ")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]!.toUpperCase())
      .join("") || "?";
  return (
    <span
      aria-hidden
      className={clsx(
        "inline-flex shrink-0 items-center justify-center rounded border border-border bg-surface-muted font-semibold text-fg-muted",
        size === "sm" && "h-6 w-6 text-2xs",
        size === "md" && "h-7 w-7 text-xs",
        size === "lg" && "h-10 w-10 text-sm",
      )}
    >
      {initials}
    </span>
  );
}
