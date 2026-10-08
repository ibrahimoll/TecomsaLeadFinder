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
      <div className="relative flex animate-page-in items-center gap-3 overflow-hidden rounded-lg border border-border bg-surface px-3.5 py-3 shadow-xs" aria-live="polite">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-success-soft text-success" aria-hidden>
          <FileSpreadsheet className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium">{file.name}</p>
          <p className="text-xs text-fg-muted">
            {busy ? "Analyzing file structure…" : formatBytes(file.size)}
          </p>
        </div>
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin text-accent" aria-label="Uploading" />
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
        {busy && (
          <span className="absolute inset-x-0 bottom-0 block h-0.5 overflow-hidden bg-accent-soft" aria-hidden>
            <span className="absolute inset-y-0 left-0 w-1/3 animate-[loading-bar_1.1s_ease-in-out_infinite] bg-accent" />
          </span>
        )}
      </div>
    );
  }

  return (
    <label
      htmlFor={id}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={clsx(
        "group flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-7 text-center transition-[background-color,border-color] duration-200 focus-within:border-accent",
        disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
        over ? "border-accent bg-accent-soft" : "border-border-strong bg-surface-muted/40 hover:border-accent/50 hover:bg-accent-soft/40",
      )}
    >
      <span
        className={clsx(
          "mb-3 flex h-11 w-11 items-center justify-center rounded-xl transition-[transform,background-color,color] duration-200",
          over ? "-translate-y-1 scale-110 bg-accent text-white" : "bg-surface text-accent shadow-xs group-hover:-translate-y-0.5",
        )}
        aria-hidden
      >
        <Upload className="h-5 w-5" />
      </span>
      <p className="text-[13px] text-fg">
        {over ? (
          <span className="font-medium text-accent">Drop to upload</span>
        ) : (
          <>
            Drag a file here, or <span className="font-medium text-accent group-hover:underline">choose a file</span>
          </>
        )}
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
    </label>
  );
}
