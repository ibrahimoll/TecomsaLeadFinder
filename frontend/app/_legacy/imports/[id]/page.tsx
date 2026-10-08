"use client";

import clsx from "clsx";
import { Building2, Check, Download, Trash2, Upload, X } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { RequireCapability } from "@/components/guard";
import { DeleteImportDialog } from "@/components/import-table";
import { ImportStatusBadge } from "@/components/status-badges";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  DataTable,
  DescriptionList,
  EmptyState,
  ErrorState,
  MetricStrip,
  PageHeader,
  Section,
  Skeleton,
  toast,
  type Tone,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { IMPORT_TYPE_LABEL } from "@/lib/constants";
import { formatBytes, formatDateTime } from "@/lib/format";
import type { ImportPreview, ImportRun } from "@/types";

type SampleRow = ImportPreview["sample_rows"][number];

const PREVIEW_COLUMNS: Record<ImportRun["import_type"], { key: string; label: string; width?: string }[]> = {
  ODOO_CONTACTS: [
    { key: "company", label: "Company", width: "max-w-[220px]" },
    { key: "contact", label: "Contact", width: "max-w-[180px]" },
    { key: "position", label: "Position", width: "max-w-[160px]" },
    { key: "phone", label: "Phone" },
    { key: "email", label: "Email", width: "max-w-[220px]" },
    { key: "country", label: "Country" },
    { key: "city", label: "City" },
  ],
  ODOO_CRM: [
    { key: "opportunity", label: "Opportunity", width: "max-w-[260px]" },
    { key: "company", label: "Customer", width: "max-w-[220px]" },
    { key: "contact", label: "Contact", width: "max-w-[180px]" },
    { key: "salesperson", label: "Salesperson" },
    { key: "stage", label: "Stage" },
  ],
};

const ROW_STATUS: Record<SampleRow["status"], { tone: Tone; label: string }> = {
  new: { tone: "success", label: "Ready" },
  update: { tone: "info", label: "Update" },
  warning: { tone: "warning", label: "Warning" },
  duplicate: { tone: "neutral", label: "Duplicate" },
  error: { tone: "danger", label: "Skipped" },
};

function Steps({ step }: { step: 1 | 2 | 3 }) {
  return (
    <ol className="mb-5 flex items-center gap-2 text-xs" aria-label="Import progress">
      {["Upload", "Preview", "Import"].map((label, i) => {
        const n = i + 1;
        const done = n < step || step === 3;
        const current = n === step && step !== 3;
        return (
          <li key={label} className="flex items-center gap-2" aria-current={current ? "step" : undefined}>
            {i > 0 && (
              <span className="h-0.5 w-8 overflow-hidden rounded-full bg-border" aria-hidden>
                <span className={clsx("block h-full bg-success transition-[width] duration-500 ease-out", n <= step ? "w-full" : "w-0")} />
              </span>
            )}
            <span className="relative flex h-6 w-6 items-center justify-center">
              {current && <span className="absolute inset-0 animate-ping rounded-full bg-accent/25 [animation-duration:2s]" aria-hidden />}
              <span
                className={clsx(
                  "relative flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold transition-colors duration-300",
                  done ? "animate-pop-in bg-success text-white" : current ? "bg-accent text-white shadow-[0_0_0_4px_rgb(var(--accent)/0.15)]" : "border border-border-strong text-fg-muted",
                )}
              >
                {done ? <Check className="h-3 w-3" strokeWidth={3} aria-hidden /> : n}
              </span>
            </span>
            <span className={clsx(current ? "font-medium text-fg" : "text-fg-muted")}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

const CONFIDENCE_TONE: Record<string, Tone> = { HIGH: "success", MEDIUM: "info", LOW: "warning", UNKNOWN: "neutral" };

function rowsText(rows: number[]): string {
  return rows.length === 0 ? "none" : rows.length === 1 ? `row ${rows[0]}` : `rows ${rows[0]}–${rows[rows.length - 1]}`;
}

/** What LeadFinder understood before anything is imported: where the table is, what each column means. */
function StructurePanel({ preview, onChanged }: { preview: ImportPreview; onChanged: () => Promise<void> }) {
  const s = preview.structure;
  const [busy, setBusy] = useState(false);
  if (!s) return null;
  async function choose(table: string) {
    setBusy(true);
    try {
      await api(`/imports/${preview.run.id}/table`, { method: "POST", body: { table } });
      toast.success("Table selected", "The preview now shows that table.");
      await onChanged();
    } catch (err) {
      toast.error("Could not use that table", err instanceof ApiError ? err.message : undefined);
    } finally {
      setBusy(false);
    }
  }
  const others = s.tables.filter((t) => !t.chosen);
  return (
    <Section
      title="Structure detected"
      description={
        <>
          LeadFinder analyzed this file automatically: <span className="font-medium text-fg">{s.fields_recognized} fields recognized</span>.
          Nothing is imported until you click Import records.
        </>
      }
    >
      <div className="space-y-3 text-[13px]">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-4">
          {[
            ["Sheet", s.sheet],
            ["Header", s.header_rows.length ? rowsText(s.header_rows) : "No header row: columns inferred from their values"],
            ["Records", `${s.data_rows.toLocaleString()} (rows ${s.first_row}–${s.last_row})`],
            ["Skipped rows", s.skipped_count ? `${s.skipped_count} (titles, notes, repeated headers)` : "none"],
          ].map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="text-[11.5px] text-fg-subtle">{k}</dt>
              <dd className="font-medium">{v}</dd>
            </div>
          ))}
        </dl>
        {(s.choice_needed || others.length > 0) && (
          <Alert tone={s.choice_needed ? "warning" : "info"} title={s.choice_needed ? "Several tables could be imported" : "Other tables in this file"}>
            <ul className="mt-1 space-y-1">
              {s.tables.map((t) => (
                <li key={t.id} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{t.sheet}</span>
                  <span className="text-fg-muted">
                    rows {t.first_row}–{t.last_row} · {t.data_rows} records{t.fields.length ? ` · ${t.fields.join(", ")}` : ""}
                  </span>
                  {t.chosen ? (
                    <Badge tone="success">Importing</Badge>
                  ) : t.usable ? (
                    <Button size="sm" variant="secondary" disabled={busy} onClick={() => void choose(t.id)}>Use this table</Button>
                  ) : (
                    <Badge>Not importable</Badge>
                  )}
                </li>
              ))}
            </ul>
          </Alert>
        )}
        <div className="overflow-x-auto rounded border border-border">
          <table className="w-full text-left text-[12.5px]">
            <thead className="bg-surface-muted/60 text-[11px] uppercase tracking-wide text-fg-subtle">
              <tr>
                <th className="px-3 py-2 font-medium">Column</th>
                <th className="px-3 py-2 font-medium">Understood as</th>
                <th className="px-3 py-2 font-medium">Confidence</th>
                <th className="px-3 py-2 font-medium">Example values</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {s.columns.map((c) => (
                <tr key={c.column}>
                  <td className="px-3 py-1.5 whitespace-nowrap">
                    <span className="font-medium">{c.column}</span>
                    {c.header && <span className="ml-1.5 text-fg-muted">“{c.header}”</span>}
                  </td>
                  <td className="px-3 py-1.5">{c.concept === "UNKNOWN" ? (
                      <span className="text-fg-subtle">Unknown — not imported</span>
                    ) : (
                      <>
                        {c.concept_label}
                        {c.imported === false && <span className="ml-1.5 text-fg-subtle">(not used by this import type)</span>}
                      </>
                    )}</td>
                  <td className="px-3 py-1.5"><Badge tone={CONFIDENCE_TONE[c.confidence] ?? "neutral"}>{c.confidence.charAt(0) + c.confidence.slice(1).toLowerCase()}</Badge></td>
                  <td className="max-w-[380px] truncate px-3 py-1.5 text-fg-muted" title={c.samples.join(" · ")}>{c.samples.join(" · ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {s.skipped_rows.length > 0 && (
          <details className="text-xs text-fg-muted">
            <summary className="cursor-pointer select-none">Skipped rows</summary>
            <ul className="mt-1 space-y-0.5">
              {s.skipped_rows.map((r) => <li key={r.row}>Row {r.row}: {r.reason}</li>)}
            </ul>
          </details>
        )}
      </div>
    </Section>
  );
}

function DetectedColumns({ preview }: { preview: ImportPreview }) {
  const found = preview.fields.filter((f) => f.column);
  const missing = preview.fields.filter((f) => !f.column && (f.required || f.important));
  return (
    <div className="space-y-1.5 text-[13px]">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-fg-muted">Detected</span>
        {found.map((f) => (
          <span key={f.key} className="inline-flex h-6 items-center gap-1 rounded-sm border border-border bg-surface px-1.5 text-xs">
            <span className="font-medium">{f.label}</span>
            {f.column !== f.label && <span className="text-fg-muted">← {f.column}</span>}
            {f.confidence && f.confidence !== "HIGH" && <Badge tone={CONFIDENCE_TONE[f.confidence] ?? "neutral"}>{f.confidence.toLowerCase()}</Badge>}
          </span>
        ))}
      </div>
      {(missing.length > 0 || preview.unmapped_columns.length > 0) && (
        <p className="text-xs text-fg-muted">
          {missing.length > 0 && <>Not in this file: {missing.map((f) => f.label).join(", ")}. </>}
          {preview.unmapped_columns.length > 0 && <>Ignored columns: {preview.unmapped_columns.join(", ")}.</>}
        </p>
      )}
    </div>
  );
}

function IssuesList({ run }: { run: ImportRun }) {
  if (run.issues.length === 0) return null;
  const tone = { error: "danger", warning: "warning", duplicate: "neutral" } as const;
  const label = { error: "Skipped", warning: "Warning", duplicate: "Duplicate" } as const;
  return (
    <details className="group rounded-lg border border-border bg-surface">
      <summary className="flex cursor-pointer select-none items-center justify-between px-4 py-2.5 text-[13px] font-medium hover:bg-surface-hover/60">
        Row notes ({run.issues.length >= 200 ? "first 200" : run.issues.length})
        <span className="text-xs font-normal text-fg-muted group-open:hidden">Show</span>
        <span className="hidden text-xs font-normal text-fg-muted group-open:inline">Hide</span>
      </summary>
      <ul className="max-h-72 divide-y divide-border overflow-y-auto border-t border-border">
        {run.issues.map((issue, i) => (
          <li key={i} className="flex items-start gap-3 px-4 py-2 text-[13px]">
            <span className="w-14 shrink-0 tabular text-fg-muted">Row {issue.row}</span>
            <Badge tone={tone[issue.level]}>{label[issue.level]}</Badge>
            <span className="min-w-0 break-words">{issue.message}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function PreviewView({ preview, onDone, onChanged }: { preview: ImportPreview; onDone: () => Promise<void>; onChanged: () => Promise<void> }) {
  const router = useRouter();
  const run = preview.run;
  const [busy, setBusy] = useState<"import" | "discard" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const columns = PREVIEW_COLUMNS[run.import_type];

  async function importRecords() {
    setBusy("import");
    setError(null);
    try {
      await api<ImportRun>(`/imports/${run.id}/confirm`, { method: "POST" });
      toast.success("Import complete", "Company relationship statuses were recalculated.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The import did not complete.");
    }
    await onDone(); // shows the result, or the recorded failure
    setBusy(null);
  }

  async function discard() {
    setBusy("discard");
    try {
      await api(`/imports/${run.id}`, { method: "DELETE" });
      toast.info("Upload discarded", "Nothing was imported.");
      router.push("/data-sources/odoo");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The preview could not be discarded.");
      setBusy(null);
    }
  }

  return (
    <>
      <Steps step={2} />
      <div className="space-y-4">
        {error && <Alert title="Import not completed">{error}</Alert>}
        {preview.previous_import && (
          <Alert tone="warning" title="This exact file was imported before">
            Imported on {formatDateTime(preview.previous_import.completed_at)}. Importing it again updates the same records instead of
            duplicating them.
          </Alert>
        )}

        <MetricStrip
          items={[
            { label: "Rows detected", value: run.row_count },
            {
              label: "Ready",
              value: run.valid_count,
              hint: `${preview.new_records.toLocaleString()} new · ${preview.existing_records.toLocaleString()} already in LeadFinder`,
            },
            { label: "Duplicates", value: run.duplicate_count, hint: "Repeated rows, skipped" },
            { label: "Warnings", value: run.warning_count, hint: "Imported with a note" },
            ...(run.error_count ? [{ label: "Skipped", value: run.error_count, hint: "No company or contact name" }] : []),
          ]}
        />

        <StructurePanel preview={preview} onChanged={onChanged} />
        <DetectedColumns preview={preview} />

        <Section
          title="Preview"
          description={
            <>
              {preview.sample_rows.length < run.row_count
                ? `First ${preview.sample_rows.length} of ${run.row_count.toLocaleString()} rows. `
                : ""}
              {preview.companies_matched.toLocaleString()} matching LeadFinder{" "}
              {preview.companies_matched === 1 ? "company" : "companies"}, {preview.companies_new.toLocaleString()} new{" "}
              {preview.companies_new === 1 ? "company" : "companies"} will be created.
            </>
          }
          flush
        >
          <DataTable
            caption="Preview of the rows to import"
            rows={preview.sample_rows}
            rowKey={(r) => r.row}
            empty={<EmptyState compact title="The file has no rows" />}
            columns={[
              { key: "row", header: "#", align: "right", cell: (r) => <span className="text-fg-subtle">{r.row}</span> },
              ...columns.map((c) => ({
                key: c.key,
                header: c.label,
                cell: (r: SampleRow) => {
                  const value = r.values[c.key];
                  return value == null || value === "" ? (
                    <span className="text-fg-subtle">—</span>
                  ) : (
                    <span className={clsx("block truncate", c.width)} title={String(value)}>
                      {String(value)}
                    </span>
                  );
                },
              })),
              {
                key: "status",
                header: "Status",
                cell: (r) => (
                  <span className="block py-1 leading-tight" title={r.messages.join("\n") || undefined}>
                    <Badge tone={ROW_STATUS[r.status].tone} dot>
                      {ROW_STATUS[r.status].label}
                    </Badge>
                    {r.messages[0] && <span className="mt-0.5 block max-w-[200px] truncate text-xs text-fg-muted">{r.messages[0]}</span>}
                  </span>
                ),
              },
            ]}
          />
        </Section>

        <IssuesList run={run} />

        <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center justify-end gap-2 border-t border-border bg-bg/95 px-4 py-3 backdrop-blur md:-mx-8 md:px-8">
          <span className="mr-auto text-[13px] text-fg-muted">
            <span className="font-medium text-fg">{run.valid_count.toLocaleString()}</span> of {run.row_count.toLocaleString()} rows will be
            imported. Company statuses are recalculated afterwards.
          </span>
          <Button variant="ghost" onClick={discard} loading={busy === "discard"} disabled={busy !== null}>
            <X className="h-3.5 w-3.5" aria-hidden /> Discard
          </Button>
          <Button onClick={importRecords} loading={busy === "import"} disabled={busy !== null || run.valid_count === 0}>
            <Download className="h-3.5 w-3.5" aria-hidden /> Import records
          </Button>
        </div>
      </div>
    </>
  );
}

function ResultView({ run }: { run: ImportRun }) {
  const router = useRouter();
  const [deleting, setDeleting] = useState(false);
  const completed = run.status === "COMPLETED";
  return (
    <>
      <Steps step={completed ? 3 : 2} />
      <div className="space-y-5">
        {completed && (
          <Alert tone="success" title={`Imported ${(run.inserted_count + run.updated_count).toLocaleString()} records`}>
            {run.inserted_count.toLocaleString()} new, {run.updated_count.toLocaleString()} updated, {run.skipped_count.toLocaleString()}{" "}
            skipped. Company relationship statuses were recalculated.
          </Alert>
        )}
        {run.status === "FAILED" && (
          <Alert title="Import failed: no records were saved">
            {run.failure_reason ?? "Unknown error."} Fix the file and upload it again.
          </Alert>
        )}
        {run.status === "CANCELLED" && <Alert tone="info" title="This import was cancelled">No records were imported.</Alert>}

        {completed && (
          <MetricStrip
            items={[
              { label: "Rows in file", value: run.row_count },
              { label: "New", value: run.inserted_count },
              { label: "Updated", value: run.updated_count },
              { label: "Skipped", value: run.skipped_count },
              { label: "Companies created", value: run.companies_created, href: "/companies?source=ODOO_IMPORT" },
              { label: "Companies linked", value: run.companies_linked },
            ]}
          />
        )}
        <Section title="Details">
          <DescriptionList
            columns={3}
            items={[
              { label: "Type", value: IMPORT_TYPE_LABEL[run.import_type] },
              { label: "File", value: `${run.original_filename} (${run.file_type.toUpperCase()}, ${formatBytes(run.file_size)})` },
              { label: "Uploaded by", value: run.creator?.name ?? "—" },
              { label: "Uploaded", value: formatDateTime(run.created_at) },
              { label: "Finished", value: formatDateTime(run.completed_at) },
              { label: "Status", value: <ImportStatusBadge status={run.status} /> },
            ]}
          />
        </Section>
        <IssuesList run={run} />
        <div className="flex flex-wrap items-center gap-2">
          <ButtonLink href="/data-sources/odoo">
            <Upload className="h-3.5 w-3.5" aria-hidden /> Import another file
          </ButtonLink>
          <ButtonLink href="/companies" variant="secondary">
            <Building2 className="h-3.5 w-3.5" aria-hidden /> View companies
          </ButtonLink>
          <Button variant="danger" className="ml-auto" onClick={() => setDeleting(true)}>
            <Trash2 className="h-3.5 w-3.5" aria-hidden /> Delete import
          </Button>
        </div>
      </div>
      <DeleteImportDialog
        run={deleting ? run : null}
        onClose={() => setDeleting(false)}
        onDeleted={() => router.push("/data-sources/odoo")}
      />
    </>
  );
}

function ImportDetail() {
  const { id } = useParams<{ id: string }>();
  const run = useApi<ImportRun>(`/imports/${id}`);
  const isPreview = run.data?.status === "PREVIEW";
  const preview = useApi<ImportPreview>(isPreview ? `/imports/${id}/preview` : null);

  const error = run.error ?? preview.error;
  if (error) return <Section><ErrorState message={error.message} onRetry={run.reload} /></Section>;
  if (!run.data || (isPreview && !preview.data)) {
    return (
      <div className="space-y-4" aria-busy="true">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  const r = run.data;
  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Data sources" }, { label: "Odoo", href: "/data-sources/odoo" }, { label: r.original_filename }]}
        title={r.original_filename}
        meta={
          <>
            <ImportStatusBadge status={r.status} />
            <span>{IMPORT_TYPE_LABEL[r.import_type]}</span>
            <span>
              {r.file_type.toUpperCase()} · {formatBytes(r.file_size)}
            </span>
          </>
        }
      />
      {isPreview && preview.data ? (
        <PreviewView
          preview={preview.data}
          onDone={run.reload}
          onChanged={async () => {
            await Promise.all([run.reload(), preview.reload()]);
          }}
        />
      ) : (
        <ResultView run={r} />
      )}
    </>
  );
}

export default function ImportDetailPage() {
  return (
    <RequireCapability capability="run_imports">
      <ImportDetail />
    </RequireCapability>
  );
}
