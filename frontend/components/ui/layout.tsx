"use client";

import clsx from "clsx";
import { Building2, ChevronRight, Search, Settings, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

/** Section icons, matching the sidebar navigation. Top-level pages show theirs in the header. */
const SECTION_ICONS: [prefix: string, icon: LucideIcon][] = [
  ["/find-leads", Search],
  ["/companies", Building2],
  ["/settings", Settings],
  ["/admin", Settings],
];

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
  const pathname = usePathname();
  // Detail pages (with breadcrumbs) carry their own identity, e.g. the company logo.
  const Icon = breadcrumbs?.length ? null : SECTION_ICONS.find(([prefix]) => pathname.startsWith(prefix))?.[1];
  return (
    <header className="relative mb-6 pb-5">
      {/* Brand rule: a short red segment that draws in over the hairline. */}
      <span className="absolute inset-x-0 bottom-0 h-px bg-border" aria-hidden />
      <span className="absolute bottom-0 left-0 h-[2px] w-16 origin-left animate-grow-x rounded-full bg-accent" aria-hidden />
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-2">
          <ol className="flex flex-wrap items-center gap-1 text-xs text-fg-subtle">
            {breadcrumbs.map((crumb, i) => (
              <li key={crumb.label} className="flex items-center gap-1">
                {i > 0 && <ChevronRight className="h-3 w-3 text-fg-subtle" aria-hidden />}
                {crumb.href ? (
                  <Link href={crumb.href} className="transition-colors hover:text-fg">
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current="page" className="text-fg-muted">{crumb.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3.5">
          {Icon && (
            <span
              className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent"
              aria-hidden
            >
              <Icon className="h-[18px] w-[18px]" strokeWidth={2} />
            </span>
          )}
          <div className="min-w-0">
          <h1 className="text-[24px] font-semibold leading-8 tracking-[-0.022em]">{title}</h1>
          {description && <p className="mt-1 max-w-2xl text-[14px] text-fg-muted">{description}</p>}
          {meta && <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px] text-fg-muted">{meta}</div>}
          </div>
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
    <section id={id} className={clsx("rounded-lg border border-border bg-surface shadow-card", className)}>
      {(title || actions) && (
        <div className="flex min-h-[52px] flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <div className="min-w-0">
            {title && <h2 className="text-[14px] font-semibold tracking-[-0.01em]">{title}</h2>}
            {description && <p className="mt-px text-xs text-fg-muted">{description}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={clsx(!flush && "p-4")}>{children}</div>
    </section>
  );
}

/** A page's primary filter as one-click pills (instead of a dropdown); the selected pill is filled red. */
export function FilterPills<V extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: V; label: string; dot?: string }[];
  value: V;
  onChange: (value: V) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="stagger flex flex-wrap gap-1.5">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className={clsx(
              "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] font-medium transition-[background-color,border-color,color,box-shadow] duration-200 active:scale-[0.97]",
              active
                ? "border-accent bg-accent text-white shadow-[0_2px_8px_-3px_rgb(var(--accent)/0.6)]"
                : "border-border bg-surface text-fg-muted hover:border-accent/40 hover:text-fg",
            )}
          >
            {o.dot && <span className={clsx("h-1.5 w-1.5 rounded-full transition-colors", active ? "bg-white" : o.dot)} aria-hidden />}
            {o.label}
          </button>
        );
      })}
    </div>
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
  icon?: LucideIcon;
}

/**
 * Accessible tabs (roving focus with arrow keys). Render panels with role="tabpanel".
 * A red indicator slides between tabs (pattern from 21st.dev "Animated Navigation Tabs").
 */
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
  const listRef = useRef<HTMLDivElement>(null);
  const [bar, setBar] = useState<{ left: number; width: number } | null>(null);
  const selectedIndex = tabs.findIndex((t) => t.key === value);
  // Re-measure when the selection or the tab labels/counts change (they change tab widths).
  const shape = tabs.map((t) => `${t.key}:${t.count ?? ""}`).join("|");

  useLayoutEffect(() => {
    function measure() {
      const el = refs.current[selectedIndex];
      const next = el ? { left: el.offsetLeft, width: el.offsetWidth } : null;
      setBar((prev) => (prev?.left === next?.left && prev?.width === next?.width ? prev : next));
    }
    measure();
    const observer = new ResizeObserver(measure);
    if (listRef.current) observer.observe(listRef.current);
    return () => observer.disconnect();
  }, [selectedIndex, shape]);

  function onKeyDown(event: KeyboardEvent, index: number) {
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    event.preventDefault();
    const next = (index + delta + tabs.length) % tabs.length;
    refs.current[next]?.focus();
    onChange(tabs[next]!.key);
  }

  return (
    <div ref={listRef} role="tablist" aria-label={label} className="relative flex gap-1 overflow-x-auto border-b border-border">
      {tabs.map((tab, i) => {
        const selected = tab.key === value;
        const Icon = tab.icon;
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
              "group relative my-1 inline-flex h-9 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-[13.5px] font-medium transition-colors duration-200",
              selected ? "text-fg" : "text-fg-muted hover:bg-surface-hover hover:text-fg",
            )}
          >
            {Icon && (
              <Icon
                className={clsx("h-3.5 w-3.5 transition-colors duration-200", selected ? "text-accent" : "text-fg-subtle group-hover:text-fg-muted")}
                aria-hidden
              />
            )}
            {tab.label}
            {tab.count !== undefined && (
              <span
                key={tab.count}
                className={clsx(
                  "min-w-[20px] animate-pop-in rounded-full px-1.5 text-center text-[11px] font-semibold tabular transition-colors duration-200",
                  selected ? "bg-accent text-white" : "bg-surface-muted text-fg-muted group-hover:bg-border",
                )}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
      {bar && (
        <span
          className="pointer-events-none absolute bottom-0 left-0 h-[2.5px] rounded-full bg-accent shadow-[0_0_8px_rgb(var(--accent)/0.5)] transition-[transform,width] duration-300 ease-out"
          style={{ width: bar.width, transform: `translateX(${bar.left}px)` }}
          aria-hidden
        />
      )}
    </div>
  );
}
