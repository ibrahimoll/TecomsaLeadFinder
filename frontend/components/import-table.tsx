"use client";

import clsx from "clsx";
import { Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { ImportStatusBadge } from "@/components/status-badges";
import { Alert, Avatar, Button, ConfirmDialog, DataTable, RowLink } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { IMPORT_TYPE_LABEL } from "@/lib/constants";
import { formatDateTime } from "@/lib/format";
import type { ImportDeleteResult, ImportRun } from "@/types";

function plural(n: number, one: string, many = `${one}s`) {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/** One sentence describing what a delete did. */
export function describeDelete(filename: string, result: ImportDeleteResult): string {
  if (!result.with_data) return `Deleted ${filename} from the import history. Imported records were kept.`;
  const { crm_records, odoo_contacts, companies, salespeople } = result.removed;
  const parts = [
    crm_records && plural(crm_records, "CRM record"),
    odoo_contacts && plural(odoo_contacts, "Odoo contact"),
    companies && plural(companies, "company", "companies"),
    salespeople && plural(salespeople, "salesperson", "salespeople"),
  ].filter(Boolean);
  const kept = result.kept.companies
    ? ` ${plural(result.kept.companies, "company", "companies")} kept because ${result.kept.companies === 1 ? "it is" : "they are"} still in use.`
    : "";
  return `Deleted ${filename}${parts.length ? ` and removed ${parts.join(", ")}` : ""}.${kept}`;
}

type Mode = "import" | "data";

function Option({
  checked,
  onSelect,
  title,
  children,
}: {
  checked: boolean;
  onSelect: () => void;
  title: string;
  children: ReactNode;
}) {
  return (
    <label
      className={clsx(
        "flex cursor-pointer gap-2.5 rounded border px-3 py-2.5 transition-colors",
        checked ? "border-fg/40 bg-surface-muted/60" : "border-border hover:bg-surface-hover/60",
      )}
    >
      <input type="radio" name="delete-mode" checked={checked} onChange={onSelect} className="mt-0.5 accent-[rgb(var(--fg))]" />
      <span>
        <span className="block font-medium text-fg">{title}</span>
        <span className="mt-0.5 block text-xs text-fg-muted">{children}</span>
      </span>
    </label>
  );
}

/** Asks how to delete an import (history only, or history + the data it brought in) and does it. */
export function DeleteImportDialog({
  run,
  onClose,
  onDeleted,
}: {
  run: ImportRun | null;
  onClose: () => void;
  onDeleted: (run: ImportRun, result: ImportDeleteResult) => void;
}) {
  const [mode, setMode] = useState<Mode>("import");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const imported = run?.status === "COMPLETED";

  async function remove() {
    if (!run) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api<ImportDeleteResult>(`/imports/${run.id}`, {
        method: "DELETE",
        query: { with_data: imported && mode === "data" },
      });
      setMode("import");
      onDeleted(run, result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The import could not be deleted.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ConfirmDialog
      open={run !== null}
      title={`Delete ${run?.original_filename ?? "import"}?`}
      tone="danger"
      confirmLabel={imported && mode === "data" ? "Delete import and data" : "Delete import"}
      busy={busy}
      onConfirm={remove}
      onClose={() => {
        setError(null);
        setMode("import");
        onClose();
      }}
    >
      <div className="space-y-2">
        {imported ? (
          <>
            <Option checked={mode === "import"} onSelect={() => setMode("import")} title="Delete import only">
              Removes this entry and the stored file. The {plural(run.inserted_count + run.updated_count, "imported record")} stay in
              LeadFinder.
            </Option>
            <Option checked={mode === "data"} onSelect={() => setMode("data")} title="Delete import and imported data">
              Also removes the contacts, CRM records and companies that came only from this import. Anything a later import also
              contains, or a company used in a campaign or with notes, is kept. Company statuses are recalculated.
            </Option>
          </>
        ) : (
          <p>This file was never imported, so no records are affected. The entry and the stored file are removed.</p>
        )}
        {error && <Alert>{error}</Alert>}
      </div>
    </ConfirmDialog>
  );
}

/** Import list shared by the Odoo imports page and the import history page. */
export function ImportsTable({
  rows,
  loading,
  error,
  onRetry,
  onChanged,
  empty,
}: {
  rows: ImportRun[] | undefined;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onChanged: () => void;
  empty: ReactNode;
}) {
  const [target, setTarget] = useState<ImportRun | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  return (
    <>
      {notice && (
        <div className="border-b border-border px-4 py-2.5">
          <Alert tone="success">{notice}</Alert>
        </div>
      )}
      <DataTable
        caption="Imports"
        rows={rows}
        loading={loading}
        error={error}
        onRetry={onRetry}
        rowKey={(r) => r.id}
        rowHref={(r) => `/imports/${r.id}`}
        empty={empty}
        columns={[
          {
            key: "file",
            header: "File",
            cell: (r) => (
              <div className="max-w-[320px] leading-tight">
                <span className="block truncate" title={r.original_filename}>
                  <RowLink href={`/imports/${r.id}`}>{r.original_filename}</RowLink>
                </span>
                <p className="text-xs text-fg-muted">{IMPORT_TYPE_LABEL[r.import_type]}</p>
              </div>
            ),
          },
          { key: "status", header: "Status", cell: (r) => <ImportStatusBadge status={r.status} /> },
          { key: "rows", header: "Rows", align: "right", cell: (r) => r.row_count.toLocaleString() },
          {
            key: "result",
            header: "Imported",
            align: "right",
            cell: (r) =>
              r.status === "COMPLETED" ? (
                <span className="inline-flex items-center gap-1.5" title={`${r.inserted_count} new, ${r.updated_count} updated`}>
                  <span className="rounded-full bg-success-soft px-2 py-0.5 font-semibold text-success">+{r.inserted_count.toLocaleString()}</span>
                  {r.updated_count > 0 && <span className="text-xs text-fg-muted">{r.updated_count.toLocaleString()} updated</span>}
                </span>
              ) : (
                <span className="text-fg-subtle">—</span>
              ),
          },
          {
            key: "skipped",
            header: "Skipped",
            align: "right",
            cell: (r) => (r.skipped_count ? <span className="font-medium text-warning">{r.skipped_count.toLocaleString()}</span> : <span className="text-fg-subtle">0</span>),
          },
          {
            key: "by",
            header: "By",
            cell: (r) =>
              r.creator ? (
                <span className="inline-flex items-center gap-2 text-fg-muted">
                  <Avatar name={r.creator.name} size="sm" /> {r.creator.name}
                </span>
              ) : (
                <span className="text-fg-subtle">—</span>
              ),
          },
          { key: "at", header: "Date", cell: (r) => <span className="text-fg-muted">{formatDateTime(r.completed_at ?? r.created_at)}</span> },
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (r) => (
              <Button
                variant="ghost"
                size="icon"
                className="hover:!text-danger"
                onClick={() => {
                  setNotice(null);
                  setTarget(r);
                }}
                aria-label={`Delete ${r.original_filename}`}
                title="Delete import"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
              </Button>
            ),
          },
        ]}
      />
      <DeleteImportDialog
        run={target}
        onClose={() => setTarget(null)}
        onDeleted={(run, result) => {
          setTarget(null);
          setNotice(describeDelete(run.original_filename, result));
          onChanged();
        }}
      />
    </>
  );
}
