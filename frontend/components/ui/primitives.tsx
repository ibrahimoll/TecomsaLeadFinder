"use client";

import clsx from "clsx";
import { Search, X } from "lucide-react";
import Link from "next/link";
import { forwardRef } from "react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const base =
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded font-medium transition-colors disabled:pointer-events-none disabled:opacity-50";
const variants: Record<Variant, string> = {
  primary: "bg-accent text-white hover:bg-accent-hover",
  secondary: "border border-border-strong bg-surface text-fg hover:bg-surface-hover",
  ghost: "text-fg-muted hover:bg-surface-hover hover:text-fg",
  danger: "border border-danger/30 bg-surface text-danger hover:bg-danger-soft",
};
const sizes: Record<Size, string> = { sm: "h-7 px-2.5 text-xs", md: "h-8 px-3 text-[13px]" };

export function buttonClass(variant: Variant = "primary", size: Size = "md", className?: string) {
  return clsx(base, variants[variant], sizes[size], className);
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return <button type={type} className={buttonClass(variant, size, className)} {...props} />;
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
  "block rounded border border-border-strong bg-surface text-[13px] text-fg placeholder:text-fg-subtle transition-colors hover:border-fg-subtle focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-muted aria-[invalid=true]:border-danger";

/** Controls fill their container unless the caller sets an explicit width (w-40, sm:w-72 …). */
function controlClass(extra: string, className?: string) {
  const hasWidth = /(^|\s|:)w-/.test(className ?? "");
  return clsx(control, !hasWidth && "w-full", extra, className);
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return <input ref={ref} className={controlClass("h-8 px-2.5", className)} {...props} />;
});

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={controlClass("h-8 pl-2.5 pr-8", className)} {...props} />;
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={controlClass("min-h-[72px] px-2.5 py-1.5", className)} {...props} />;
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
        className={clsx(control, "h-8 w-full pl-8 pr-7 [&::-webkit-search-cancel-button]:hidden")}
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Clear search"
          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-fg-subtle hover:text-fg"
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
    <label className={clsx("inline-flex cursor-pointer items-center gap-2 text-[13px] text-fg", className)}>
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
      <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-fg">
        {label}
        {required && (
          <span className="ml-0.5 text-danger" aria-hidden>
            *
          </span>
        )}
      </label>
      {children}
      {error ? (
        <p id={messageId} role="alert" className="mt-1 text-xs text-danger">
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

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded-sm border border-border bg-surface-muted px-1 font-mono text-2xs text-fg-muted">{children}</kbd>
  );
}
