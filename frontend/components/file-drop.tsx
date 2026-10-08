"use client";

import clsx from "clsx";
import { FileSpreadsheet, Loader2, Upload, X } from "lucide-react";
import { useId, useState, type DragEvent } from "react";

import { formatBytes } from "@/lib/format";

const ACCEPT = ".csv,.xlsx";
const MAX_BYTES = 20 * 1024 * 1024;

/** Accessible file picker with drag-and-drop. Validates extension and size client-side. */
export function FileDrop({
  file,
  onFile,
  disabled,
  busy,
}: {
  file: File | null;
  onFile: (file: File | null, error?: string) => void;
  disabled?: boolean;
  /** Shown while the chosen file is being uploaded and checked. */
  busy?: boolean;
}) {
  const id = useId();
  const [over, setOver] = useState(false);

  function choose(f: File | undefined | null) {
    if (!f) return;
    const name = f.name.toLowerCase();
    if (name.endsWith(".xls")) return onFile(null, "Legacy .xls files are not supported. Save the file as .xlsx or export CSV from Odoo.");
    if (!name.endsWith(".csv") && !name.endsWith(".xlsx")) return onFile(null, "Choose a .csv or .xlsx file exported from Odoo.");
    if (f.size > MAX_BYTES) return onFile(null, `The file is ${formatBytes(f.size)}; the limit is 20 MB.`);
    onFile(f);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    if (!disabled) choose(e.dataTransfer.files?.[0]);
  }

  if (file) {
    return (
      <div className="flex items-center gap-3 rounded border border-border bg-surface-muted/60 px-3 py-2.5" aria-live="polite">
        <FileSpreadsheet className="h-5 w-5 shrink-0 text-fg-subtle" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium">{file.name}</p>
          <p className="text-xs text-fg-muted">
            {busy ? "Reading the file and detecting columns…" : formatBytes(file.size)}
          </p>
        </div>
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin text-fg-muted" aria-label="Uploading" />
        ) : (
        <button
          type="button"
          onClick={() => onFile(null)}
          disabled={disabled}
          className="rounded p-1 text-fg-subtle hover:bg-surface-hover hover:text-fg"
          aria-label={`Remove ${file.name}`}
        >
          <X className="h-4 w-4" />
        </button>
        )}
      </div>
    );
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={clsx(
        "flex flex-col items-center justify-center rounded border border-dashed px-4 py-5 text-center transition-colors",
        over ? "border-accent bg-accent-soft" : "border-border-strong bg-surface-muted/40",
      )}
    >
      <Upload className="mb-2 h-5 w-5 text-fg-subtle" aria-hidden />
      <p className="text-[13px] text-fg">
        Drag a file here, or{" "}
        <label htmlFor={id} className="cursor-pointer font-medium text-accent hover:underline">
          choose a file
        </label>
      </p>
      <p className="mt-0.5 text-xs text-fg-muted">CSV or XLSX, up to 20 MB</p>
      <input
        id={id}
        type="file"
        accept={ACCEPT}
        disabled={disabled}
        className="sr-only"
        onChange={(e) => {
          choose(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
    </div>
  );
}
