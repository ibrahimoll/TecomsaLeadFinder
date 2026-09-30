"use client";

import clsx from "clsx";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
  breadcrumbs,
  meta,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumbs?: { label: string; href?: string }[];
  meta?: ReactNode;
}) {
  return (
    <header className="mb-5">
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-1.5">
          <ol className="flex flex-wrap items-center gap-1 text-xs text-fg-muted">
            {breadcrumbs.map((crumb, i) => (
              <li key={crumb.label} className="flex items-center gap-1">
                {i > 0 && <ChevronRight className="h-3 w-3 text-fg-subtle" aria-hidden />}
                {crumb.href ? (
                  <Link href={crumb.href} className="hover:text-fg">
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current="page">{crumb.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold leading-7 tracking-[-0.01em]">{title}</h1>
          {description && <p className="mt-0.5 text-[13px] text-fg-muted">{description}</p>}
          {meta && <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px] text-fg-muted">{meta}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

/** Bordered content surface with an optional header row. */
export function Section({
  title,
  description,
  actions,
  children,
  flush,
  className,
  id,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={clsx("rounded-lg border border-border bg-surface", className)}>
      {(title || actions) && (
        <div className="flex min-h-[44px] flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2">
          <div className="min-w-0">
            {title && <h2 className="text-[13px] font-semibold">{title}</h2>}
            {description && <p className="text-xs text-fg-muted">{description}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={clsx(!flush && "p-4")}>{children}</div>
    </section>
  );
}

export function Toolbar({ children, end }: { children: ReactNode; end?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start gap-2 border-b border-border px-4 py-2.5">
      <div className="flex flex-1 flex-wrap items-center gap-2">{children}</div>
      {end && <div className="flex items-center gap-2">{end}</div>}
    </div>
  );
}

export interface TabItem<K extends string> {
  key: K;
  label: string;
  count?: number;
}

/** Accessible tabs (roving focus with arrow keys). Render panels with role="tabpanel". */
export function Tabs<K extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  label: string;
}) {
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(event: KeyboardEvent, index: number) {
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    event.preventDefault();
    const next = (index + delta + tabs.length) % tabs.length;
    refs.current[next]?.focus();
    onChange(tabs[next]!.key);
  }

  return (
    <div role="tablist" aria-label={label} className="flex gap-4 overflow-x-auto border-b border-border">
      {tabs.map((tab, i) => {
        const selected = tab.key === value;
        return (
          <button
            key={tab.key}
            ref={(el) => {
              refs.current[i] = el;
            }}
            id={`${id}-${tab.key}`}
            role="tab"
            type="button"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onKeyDown={(e) => onKeyDown(e, i)}
            onClick={() => onChange(tab.key)}
            className={clsx(
              "-mb-px inline-flex h-9 items-center gap-1.5 whitespace-nowrap border-b-2 text-[13px] font-medium transition-colors",
              selected ? "border-fg text-fg" : "border-transparent text-fg-muted hover:text-fg",
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="rounded-sm bg-surface-muted px-1 text-2xs tabular text-fg-muted">{tab.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
