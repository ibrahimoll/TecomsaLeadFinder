"use client";

import clsx from "clsx";
import { Check } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { RequireCapability } from "@/components/guard";
import { ImportStatusBadge } from "@/components/status-badges";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  ConfirmDialog,
  DataTable,
  DescriptionList,
  EmptyState,
  ErrorState,
  MetricStrip,
  PageHeader,
  RowLink,
  Section,
  Select,
  Skeleton,
  type Tone,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { IMPORT_TYPE_LABEL } from "@/lib/constants";
import { formatBytes, formatDateTime } from "@/lib/format";
import type { ImportPreview, ImportRun } from "@/types";

const SAMPLE_FIELDS: Record<ImportRun["import_type"], { key: string; label: string }[]> = {
  ODOO_CRM: [
    { key: "opportunity_name", label: "Opportunity" },
    { key: "company_name", label: "Customer" },
    { key: "salesperson", label: "Salesperson" },
    { key: "stage", label: "Stage" },
  ],
  ODOO_CONTACTS: [
    { key: "contact_name", label: "Name" },
    { key: "parent_company", label: "Company" },
    { key: "email", label: "Email" },
    { key: "salesperson", label: "Salesperson" },
  ],
};

const ROW_STATUS: Record<string, { tone: Tone; label: string }> = {
  new: { tone: "success", label: "New" },
  update: { tone: "info", label: "Update" },
  warning: { tone: "warning", label: "Warning" },
  error: { tone: "danger", label: "Error" },
  duplicate: { tone: "neutral", label: "Duplicate" },
};

function Stepper({ step }: { step: 1 | 2 | 3 }) {
  const steps = ["Upload file", "Review & map columns", "Import"];
  return (
    <ol className="mb-5 flex flex-wrap items-center gap-2 text-[13px]" aria-label="Import progress">
      {steps.map((label, i) => {
        const n = i + 1;
        const done = n < step;
        const current = n === step;
        return (
          <li key={label} className="flex items-center gap-2" aria-current={current ? "step" : undefined}>
            {i > 0 && <span className="h-px w-6 bg-border-strong" aria-hidden />}
            <span
              className={clsx(
                "flex h-5 w-5 items-center justify-center rounded-full text-2xs font-semibold",
                done && "bg-fg text-white",
                current && "bg-accent text-white",
                !done && !current && "border border-border-strong text-fg-muted",
              )}
            >
              {done ? <Check className="h-3 w-3" aria-hidden /> : n}
            </span>
            <span className={clsx(current ? "font-medium text-fg" : "text-fg-muted")}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function MappingEditor({ preview, onApplied }: { preview: ImportPreview; onApplied: (p: ImportPreview) => void }) {
  const initial = useMemo(
    () => Object.fromEntries(preview.fields.map((f) => [f.key, f.column ?? ""])),
    [preview.fields],
  );
  const [mapping, setMapping] = useState<Record<string, string>>(initial);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => setMapping(initial), [initial]);
  const dirty = JSON.stringify(mapping) !== JSON.stringify(initial);
  const used = new Set(Object.values(mapping).filter(Boolean));

  async function apply() {
    setSaving(true);
    setError(null);
    try {
      const body = { mapping: Object.fromEntries(Object.entries(mapping).map(([k, v]) => [k, v || null])) };
      onApplied(await api<ImportPreview>(`/imports/${preview.run.id}/mapping`, { method: "PUT", body }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not apply the mapping.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section
      title="Column mapping"
      description="Detected automatically from the column headers. Adjust if your export uses different names."
      flush
      actions={
        <Button size="sm" onClick={apply} disabled={!dirty || saving}>
          {saving ? "Re-checking…" : "Apply mapping"}
        </Button>
      }
    >
      {error && (
        <div className="px-4 pt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="grid grid-cols-1 gap-x-8 gap-y-2 p-4 md:grid-cols-2">
        {preview.fields.map((field) => (
          <div key={field.key} className="flex items-center gap-3">
            <label htmlFor={`map-${field.key}`} className="w-44 shrink-0 text-[13px]">
              {field.label}
              {field.required && <span className="ml-0.5 text-danger" aria-label="required">*</span>}
            </label>
            <Select
              id={`map-${field.key}`}
              value={mapping[field.key] ?? ""}
              onChange={(e) => setMapping((m) => ({ ...m, [field.key]: e.target.value }))}
              className={clsx(!mapping[field.key] && (field.required || field.important) && "border-warning/60")}
            >
              <option value="">Not mapped</option>
              {preview.run.detected_columns.map((column) => (
                <option key={column} value={column} disabled={used.has(column) && mapping[field.key] !== column}>
                  {column}
                </option>
              ))}
            </Select>
          </div>
        ))}
      </div>
      {preview.unmapped_columns.length > 0 && (
        <p className="border-t border-border px-4 py-2.5 text-xs text-fg-muted">
          Ignored columns: {preview.unmapped_columns.join(", ")}
        </p>
      )}
    </Section>
  );
}

function IssuesList({ run }: { run: ImportRun }) {
  if (run.issues.length === 0) return null;
  const tone = { error: "danger", warning: "warning", duplicate: "neutral" } as const;
  return (
    <Section title="Row issues" description={run.issues.length >= 200 ? "Showing the first 200 issues." : undefined} flush>
      <ul className="max-h-72 divide-y divide-border overflow-y-auto">
        {run.issues.map((issue, i) => (
          <li key={i} className="flex items-start gap-3 px-4 py-2 text-[13px]">
            <span className="w-16 shrink-0 tabular text-fg-muted">Row {issue.row}</span>
            <Badge tone={tone[issue.level]}>{issue.level}</Badge>
            <span className="min-w-0 break-words">{issue.message}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function PreviewView({
  preview,
  setPreview,
  onDone,
}: {
  preview: ImportPreview;
  setPreview: (p: ImportPreview) => void;
  onDone: () => Promise<void>;
}) {
  const run = preview.run;
  const [dialog, setDialog] = useState<"confirm" | "cancel" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fields = SAMPLE_FIELDS[run.import_type];

  async function act(action: "confirm" | "cancel") {
    setBusy(true);
    setError(null);
    try {
      await api<ImportRun>(`/imports/${run.id}/${action}`, { method: "POST" });
      setDialog(null);
      await onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The request failed.");
      setBusy(false);
      setDialog(null);
      await onDone(); // an unexpected failure is recorded on the run; show it
    }
  }

  return (
    <>
      <Stepper step={2} />
      <div className="space-y-5">
        {error && <Alert title="Import not completed">{error}</Alert>}
        {preview.previous_import && (
          <Alert tone="warning" title="This exact file was imported before">
            It was imported on {formatDateTime(preview.previous_import.completed_at)} (import #{preview.previous_import.id}). Importing it
            again only refreshes the same records.
          </Alert>
        )}
        {preview.missing_important.length > 0 && (
          <Alert tone="warning" title="Some useful fields are not mapped">
            {preview.missing_important.join(", ")}. Map them below if the file contains them.
          </Alert>
        )}

        <MetricStrip
          items={[
            { label: "Rows in file", value: run.row_count },
            { label: "Ready to import", value: run.valid_count },
            { label: "New records", value: preview.new_records },
            { label: "Updates", value: preview.existing_records },
            { label: "Duplicates skipped", value: run.duplicate_count },
            { label: "Errors", value: run.error_count },
            { label: "Warnings", value: run.warning_count },
          ]}
        />
        <p className="text-[13px] text-fg-muted">
          Companies: <span className="font-medium text-fg">{preview.companies_matched}</span> match existing LeadFinder companies,{" "}
          <span className="font-medium text-fg">{preview.companies_new}</span> will be created. Matching uses Odoo ID, website and email
          domain, phone and normalised name.
        </p>

        <MappingEditor preview={preview} onApplied={setPreview} />

        <Section title="Sample rows" description={`First ${preview.sample_rows.length} rows as LeadFinder will read them.`} flush>
          <DataTable
            caption="Sample rows"
            rows={preview.sample_rows}
            rowKey={(r) => r.row}
            empty={<EmptyState compact title="No rows" />}
            columns={[
              { key: "row", header: "Row", align: "right", cell: (r) => r.row },
              { key: "status", header: "Result", cell: (r) => <Badge tone={ROW_STATUS[r.status]!.tone} dot>{ROW_STATUS[r.status]!.label}</Badge> },
              ...fields.map((f) => ({
                key: f.key,
                header: f.label,
                cell: (r: ImportPreview["sample_rows"][number]) => (
                  <span className="block max-w-[220px] truncate">{r.values[f.key] == null ? "—" : String(r.values[f.key])}</span>
                ),
              })),
              {
                key: "match",
                header: "LeadFinder company",
                cell: (r) =>
                  r.company_match ? (
                    <span title={r.company_match.reason}>
                      <RowLink href={`/companies/${r.company_match.id}`}>{r.company_match.name}</RowLink>
                    </span>
                  ) : (
                    <span className="text-fg-muted">{r.status === "error" ? "—" : "New / none"}</span>
                  ),
              },
              {
                key: "notes",
                header: "Notes",
                cell: (r) => <span className="block max-w-[280px] truncate text-xs text-fg-muted" title={r.messages.join("\n")}>{r.messages.join("; ") || "—"}</span>,
              },
            ]}
          />
        </Section>

        <IssuesList run={run} />

        <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center justify-end gap-2 border-t border-border bg-bg/95 px-4 py-3 md:-mx-8 md:px-8">
          <span className="mr-auto text-[13px] text-fg-muted">
            {run.valid_count.toLocaleString()} of {run.row_count.toLocaleString()} rows will be imported.
          </span>
          <Button variant="secondary" onClick={() => setDialog("cancel")} disabled={busy}>
            Cancel import
          </Button>
          <Button onClick={() => setDialog("confirm")} disabled={busy || run.valid_count === 0}>
            Import {run.valid_count.toLocaleString()} records
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={dialog === "confirm"}
        title={`Import ${run.valid_count.toLocaleString()} records?`}
        confirmLabel="Import"
        busy={busy}
        onConfirm={() => act("confirm")}
        onClose={() => setDialog(null)}
      >
        {preview.new_records} new and {preview.existing_records} updated {IMPORT_TYPE_LABEL[run.import_type].toLowerCase()}.{" "}
        {run.duplicate_count + run.error_count} rows will be skipped. Every company&apos;s TECOMSA relationship status is recalculated
        afterwards.
      </ConfirmDialog>
      <ConfirmDialog
        open={dialog === "cancel"}
        title="Cancel this import?"
        confirmLabel="Cancel import"
        tone="danger"
        busy={busy}
        onConfirm={() => act("cancel")}
        onClose={() => setDialog(null)}
      >
        Nothing from this file will be imported. The upload stays in the import history as cancelled.
      </ConfirmDialog>
    </>
  );
}

function ResultView({ run }: { run: ImportRun }) {
  return (
    <>
      <Stepper step={run.status === "COMPLETED" ? 3 : 2} />
      <div className="space-y-5">
        {run.status === "COMPLETED" && (
          <Alert tone="success" title="Import completed">
            Company relationship statuses have been recalculated from the latest Odoo data.
          </Alert>
        )}
        {run.status === "FAILED" && (
          <Alert title="Import failed: no records were saved">
            {run.failure_reason ?? "Unknown error."} Fix the file or mapping and upload it again.
          </Alert>
        )}
        {run.status === "CANCELLED" && <Alert tone="info" title="This import was cancelled">No records were imported.</Alert>}

        {run.status === "COMPLETED" && (
          <MetricStrip
            items={[
              { label: "Rows in file", value: run.row_count },
              { label: "Inserted", value: run.inserted_count },
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
        <div className="flex flex-wrap gap-2">
          <ButtonLink href="/companies?protected=true" variant="secondary">Protected companies</ButtonLink>
          <ButtonLink href="/crm" variant="secondary">CRM records</ButtonLink>
          <ButtonLink href="/data-sources/odoo">Import another file</ButtonLink>
        </div>
      </div>
    </>
  );
}

function ImportDetail() {
  const { id } = useParams<{ id: string }>();
  const run = useApi<ImportRun>(`/imports/${id}`);
  const isPreview = run.data?.status === "PREVIEW";
  const previewReq = useApi<ImportPreview>(isPreview ? `/imports/${id}/preview` : null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  useEffect(() => setPreview(previewReq.data), [previewReq.data]);

  const error = run.error ?? previewReq.error;
  if (error) return <Section><ErrorState message={error.message} onRetry={run.reload} /></Section>;
  if (!run.data || (isPreview && !preview)) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  const r = preview?.run ?? run.data;
  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Data sources" }, { label: "Odoo", href: "/data-sources/odoo" }, { label: `Import #${r.id}` }]}
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
      {isPreview && preview ? (
        <PreviewView preview={preview} setPreview={setPreview} onDone={run.reload} />
      ) : (
        <ResultView run={run.data} />
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
