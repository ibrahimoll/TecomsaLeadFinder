import clsx from "clsx";
import type { CSSProperties } from "react";

/** Blip positions (percent of the radar) and their ping delays: fixed, so the scan reads as data, not noise. */
const BLIPS = [
  { top: 22, left: 64, delay: 0 },
  { top: 58, left: 78, delay: 0.7 },
  { top: 70, left: 34, delay: 1.4 },
  { top: 36, left: 26, delay: 2.1 },
  { top: 46, left: 55, delay: 2.6 },
  { top: 28, left: 40, delay: 0.35 },
  { top: 66, left: 60, delay: 1.05 },
  { top: 50, left: 18, delay: 1.75 },
];

/**
 * Radar. Motion always means something real:
 *   scanning  - continuous sweep and pings while a scan actually runs
 *   pulseKey  - one sweep each time the search inputs change (a preview of the scan you are setting up)
 *   blips     - how many blips to show (e.g. the requested company count, scaled)
 * Pure CSS; the global prefers-reduced-motion rule freezes it.
 */
export function RadarScope({
  scanning,
  pulseKey,
  blips = 5,
  className,
}: {
  scanning: boolean;
  pulseKey?: string;
  blips?: number;
  className?: string;
}) {
  const sweep = "conic-gradient(from 0deg, transparent 0deg, rgb(255 255 255 / 0.38) 50deg, transparent 70deg)";
  return (
    <div className={clsx("relative aspect-square w-full max-w-[200px]", className)} aria-hidden>
      {[100, 72, 44].map((size) => (
        <span
          key={size}
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/20"
          style={{ width: `${size}%`, height: `${size}%` }}
        />
      ))}
      <span className="absolute inset-x-0 top-1/2 h-px bg-white/10" />
      <span className="absolute inset-y-0 left-1/2 w-px bg-white/10" />
      {scanning ? (
        <span
          className="absolute inset-0 animate-[fade-in_200ms_ease-out] rounded-full"
          style={{ background: sweep, animation: "spin 1.4s linear infinite" }}
        />
      ) : (
        pulseKey !== undefined && (
          // Re-keyed on every input change, so the one-shot sweep replays.
          <span key={pulseKey} className="absolute inset-0 rounded-full" style={{ background: sweep, animation: "radar-sweep 1.1s cubic-bezier(0.4, 0, 0.2, 1) forwards" }} />
        )
      )}
      {BLIPS.slice(0, Math.max(1, Math.min(BLIPS.length, blips))).map((b) => (
        <span key={`${b.top}-${b.left}`} className="absolute h-2 w-2 animate-pop-in" style={{ top: `${b.top}%`, left: `${b.left}%` }}>
          {scanning ? (
            <span className="absolute inset-0 animate-ping rounded-full bg-white/70" style={{ animationDelay: `${b.delay}s`, animationDuration: "2.8s" } as CSSProperties} />
          ) : (
            pulseKey !== undefined && (
              <span
                key={pulseKey}
                className="absolute inset-0 rounded-full bg-white/70"
                style={{ animation: `ping 1s cubic-bezier(0, 0, 0.2, 1) ${(b.delay % 1) * 0.6}s 1 both` }}
              />
            )
          )}
          <span className="absolute inset-[2px] rounded-full bg-white" />
        </span>
      ))}
      <span className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow-[0_0_0_4px_rgb(255_255_255/0.25)]" />
    </div>
  );
}
