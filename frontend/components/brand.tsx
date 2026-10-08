import clsx from "clsx";

/**
 * TECOMSA brand mark: the pixel cluster that sits above-left of the "Tecomsa" wordmark.
 * ponytail: hand-traced from the company profile PDF; replace with the official SVG when available.
 */
export function TecomsaMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 22 12" className={clsx("shrink-0", className)} fill="currentColor" aria-hidden>
      <rect x="0" y="9" width="1.6" height="1.6" />
      <rect x="4" y="5.5" width="2.2" height="2.2" />
      <rect x="8.5" y="1" width="2.4" height="2.4" />
      <rect x="11" y="7" width="2.6" height="2.6" />
      <rect x="15.5" y="3" width="2.8" height="2.8" />
      <rect x="19" y="0" width="3" height="3" />
    </svg>
  );
}

/** Full lockup: pixel mark + "Tecomsa" wordmark, optional product name / tagline underneath. */
export function TecomsaLogo({
  subtitle,
  inverted,
  compact,
  size = "md",
  className,
}: {
  size?: "md" | "lg";
  subtitle?: string;
  /** White version for red/dark backgrounds. */
  inverted?: boolean;
  /** Mark only (collapsed sidebar). */
  compact?: boolean;
  className?: string;
}) {
  if (compact) {
    return (
      <span
        className={clsx("flex h-8 w-8 items-center justify-center rounded-md bg-accent text-white shadow-[0_1px_2px_rgb(var(--accent)/0.3)]", className)}
        aria-hidden
      >
        <span className="font-display text-[15px] font-semibold leading-none">T</span>
      </span>
    );
  }
  return (
    <span className={clsx("flex items-start gap-1", inverted ? "text-white" : "text-fg", className)}>
      <TecomsaMark
        className={clsx(size === "lg" ? "mt-[5px] h-[14px] w-[27px]" : "mt-[3px] h-[9px] w-[17px]", inverted ? "text-white" : "text-accent")}
      />
      <span className="flex flex-col leading-none">
        <span className={clsx("font-display font-medium tracking-[-0.02em]", size === "lg" ? "text-[32px]" : "text-[19px]")}>Tecomsa</span>
        {subtitle && (
          <span className={clsx("mt-1 font-medium tracking-[0.02em]", size === "lg" ? "ml-0.5 text-[13px]" : "text-[10.5px]", inverted ? "text-white/75" : "text-fg-muted")}>{subtitle}</span>
        )}
      </span>
    </span>
  );
}
