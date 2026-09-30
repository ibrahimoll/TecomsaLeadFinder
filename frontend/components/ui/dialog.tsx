"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { Button } from "./primitives";

/**
 * Confirmation dialog built on the native <dialog> element, which provides focus
 * trapping, Escape to close and an inert background without extra dependencies.
 */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = "Confirm",
  tone = "primary",
  busy,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  children?: ReactNode;
  confirmLabel?: string;
  tone?: "primary" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={(e) => {
        if (busy) e.preventDefault();
      }}
      aria-labelledby="confirm-title"
      className="w-[min(440px,calc(100vw-2rem))] rounded-lg border border-border bg-surface p-0 text-fg"
    >
      <div className="px-5 pb-4 pt-5">
        <h2 id="confirm-title" className="text-[15px] font-semibold">
          {title}
        </h2>
        {children && <div className="mt-2 text-[13px] text-fg-muted">{children}</div>}
      </div>
      <div className="flex justify-end gap-2 border-t border-border bg-surface-muted/60 px-5 py-3">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant={tone === "danger" ? "danger" : "primary"} onClick={onConfirm} disabled={busy} autoFocus>
          {busy ? "Working…" : confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
