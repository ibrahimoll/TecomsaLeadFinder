"use client";

import clsx from "clsx";
import { Check, Copy, Loader2, Search, X } from "lucide-react";
import Link from "next/link";
import { forwardRef, useState } from "react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

/**
 * Button hierarchy: primary (one main action per view) · secondary (bordered) ·
 * ghost (tertiary, low emphasis) · danger (outlined trigger for a destructive action) ·
 * danger-solid (only the final confirmation of a destructive action).
 */
type Variant = "primary" | "secondary" | "ghost" | "danger" | "danger-solid";
/** `icon`: square icon-only button (needs an aria-label). */
type Size = "sm" | "md" | "icon";

const base =
  "inline-flex shrink-0 select-none items-center justify-center gap-1.5 whitespace-nowrap rounded font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-45";
const variants: Record<Variant, string> = {
  primary: "bg-accent text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.14),0_1px_2px_rgb(var(--accent)/0.3)] hover:bg-accent-hover hover:shadow-[0_3px_10px_-4px_rgb(var(--accent)/0.5)]",
  secondary: "border border-border-strong bg-surface text-fg shadow-xs hover:border-fg-subtle/60 hover:bg-surface-hover",
  ghost: "text-fg-muted hover:bg-surface-hover hover:text-fg",
  danger: "border border-danger/30 bg-surface text-danger hover:bg-danger-soft",
  "danger-solid": "bg-danger text-white hover:bg-danger/90",
};
const sizes: Record<Size, string> = { sm: "h-8 px-3 text-[12.5px]", md: "h-9 px-3.5 text-[13.5px]", icon: "h-7 w-7 px-0" };

export function buttonClass(variant: Variant = "primary", size: Size = "md", className?: string) {
  return clsx(base, variants[variant], sizes[size], className);
}

/** `loading` keeps the label (so the width does not jump), adds a spinner and disables the button. */
export function Button({
  variant = "primary",
  size = "md",
  className,
  type = "button",
  loading,
  disabled,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean }) {
  return (
    <button
      type={type}
      // While loading, the spinner replaces the button's own icon(s); the label stays so the width does not jump.
      className={buttonClass(variant, size, clsx(loading && "[&>svg~svg]:hidden", className))}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function ButtonLink({
  href,
  variant = "primary",
  size = "md",
  children,
  className,
}: {
  href: string;
  variant?: Variant;
  size?: Size;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)}>
      {children}
    </Link>
  );
}

const control =
  "block rounded border border-border-strong bg-surface text-[13.5px] text-fg shadow-xs placeholder:text-fg-subtle transition-[border-color,box-shadow] hover:border-fg-subtle/70 focus:border-accent focus:outline-none focus:ring-[3px] focus:ring-accent/20 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-fg-muted aria-[invalid=true]:border-danger";

/** Controls fill their container unless the caller sets an explicit width (w-40, sm:w-72 …). */
function controlClass(extra: string, className?: string) {
  const hasWidth = /(^|\s|:)w-/.test(className ?? "");
  return clsx(control, !hasWidth && "w-full", extra, className);
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return <input ref={ref} className={controlClass("h-9 px-3", className)} {...props} />;
});

/** Native select (keyboard, mobile pickers, a11y for free) with the product's own chevron. */
export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={controlClass("select-chevron h-9 appearance-none pl-3 pr-8", className)} {...props} />;
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={controlClass("min-h-[80px] px-3 py-2", className)} {...props} />;
}

export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  className,
  label = "Search",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  label?: string;
}) {
  return (
    <div className={clsx("relative", className)}>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" aria-hidden />
      <input
        type="search"
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={clsx(control, "h-9 w-full pl-8 pr-7 [&::-webkit-search-cancel-button]:hidden")}
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Clear search"
          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-fg-subtle hover:bg-surface-hover hover:text-fg"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

export function Checkbox({
  label,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return (
    <label className={clsx("inline-flex cursor-pointer select-none items-center gap-2 text-[13px] text-fg", className)}>
      <input type="checkbox" className="h-3.5 w-3.5 rounded-sm border-border-strong accent-[rgb(var(--accent))]" {...props} />
      {label}
    </label>
  );
}

export function Field({
  label,
  htmlFor,
  required,
  error,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor?: string;
  required?: boolean;
  error?: string;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const messageId = htmlFor ? `${htmlFor}-message` : undefined;
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="mb-1.5 block text-xs font-medium text-fg">
        {label}
        {required && (
          <span className="ml-0.5 text-fg-subtle" aria-hidden>
            *
          </span>
        )}
      </label>
      {children}
      {error ? (
        <p id={messageId} role="alert" className="mt-1 animate-page-in text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={messageId} className="mt-1 text-xs text-fg-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={clsx(
        "inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-sm border border-border bg-surface px-1 font-mono text-[10px] font-medium text-fg-muted shadow-[0_1px_0_rgb(var(--border))]",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

/** Small CSS-only tooltip for icon buttons and truncated values (hover after a short delay, or keyboard focus). */
export function Tooltip({ label, children, side = "top" }: { label: string; children: ReactNode; side?: "top" | "bottom" }) {
  return (
    <span className="group/tip relative inline-flex">
      {children}
      <span
        role="tooltip"
        className={clsx(
          "pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded bg-ink px-2 py-1 text-[11px] font-medium text-white opacity-0 transition-opacity group-hover/tip:opacity-100 group-hover/tip:delay-300 group-focus-within/tip:opacity-100",
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
        )}
      >
        {label}
      </span>
    </span>
  );
}

/** Copies a value (phone, email, id) with inline confirmation. Visible on row/field hover (parent `group`). */
/** Copies text. The Clipboard API exists only on https / localhost, and LeadFinder is opened over the office network
 * on plain http (192.168...), so the old selection + copy command is the fallback that works there. */
export function copyText(value: string): boolean {
  if (window.isSecureContext && navigator.clipboard) {
    void navigator.clipboard.writeText(value);
    return true;
  }
  const area = document.createElement("textarea");
  area.value = value;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label={copied ? "Copied" : `Copy ${label}`}
      title={copied ? "Copied" : `Copy ${label}`}
      onClick={(e) => {
        e.stopPropagation();
        e.preventDefault();
        if (copyText(value)) {
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        }
      }}
      className="rounded p-1 text-fg-subtle transition-colors hover:bg-surface-hover hover:text-accent"
    >
      {copied ? <Check className="h-3 w-3 text-accent" aria-hidden /> : <Copy className="h-3 w-3" aria-hidden />}
    </button>
  );
}
