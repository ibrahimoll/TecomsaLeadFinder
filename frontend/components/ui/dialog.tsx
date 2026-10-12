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
  confirmDisabled,
  onConfirm,
  onClose,
  alternative,
}: {
  open: boolean;
  title: string;
  children?: ReactNode;
  confirmLabel?: string;
  tone?: "primary" | "danger";
  busy?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onClose: () => void;
  /** A gentler way to get what the user wants ("Archive instead"), offered next to the destructive action. */
  alternative?: { label: string; onClick: () => void };
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
      className="elevated w-[min(460px,calc(100vw-2rem))] rounded-lg border-0 bg-surface p-0 text-fg"
    >
      <div className="px-5 pb-4 pt-5">
        <h2 id="confirm-title" className="text-[15px] font-semibold">
          {title}
        </h2>
        {children && <div className="mt-2 text-[13px] text-fg-muted">{children}</div>}
      </div>
      <div className="flex justify-end gap-2 border-t border-border bg-surface-muted/50 px-5 py-3">
        <Button variant="secondary" onClick={onClose} disabled={busy} autoFocus={tone === "danger"}>
          Cancel
        </Button>
        {alternative && (
          <Button variant="secondary" onClick={alternative.onClick} disabled={busy}>
            {alternative.label}
          </Button>
        )}
        <Button
          variant={tone === "danger" ? "danger-solid" : "primary"}
          onClick={onConfirm}
          loading={busy}
          disabled={confirmDisabled}
          autoFocus={tone !== "danger"} // a destructive dialog opens on Cancel, never on Delete
        >
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
