"use client";

import clsx from "clsx";
import { ArrowRight, Building2, ChevronDown, FileSpreadsheet, Mail, MessageCircle, Phone, ShieldCheck, Smartphone, Upload, UserRound, XCircle, type LucideIcon } from "lucide-react";
import { useRef, useState } from "react";

import { RequireCapability } from "@/components/guard";
import { Alert, Badge, Button, ConfirmDialog, DataTable, EmptyState, FilterPills, Input, Meter, MetricStrip, PageHeader, Section, TimeAgo, toast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";

interface Summary {
  rows: number;
  companies_new: number;
  companies_existing: number;
  people: number;
  people_new: number;
  mobiles: number;
  whatsapp?: number;
  phones: number;
  emails: number;
  rows_skipped: number;
}
interface Preview {
  file: string;
  summary: Summary;
  columns: { detected: Record<string, string>; ignored: string[]; unrecognised: string[] };
  review: { line: number; company?: string; person?: string; reason: string }[];
}
interface ImportRow {
  import_id: string;
  directory: string | null;
  file: string | null;
  created_at: string;
  user: string | null;
  summary: Summary;
  removed_at: string | null;
}

interface Coverage {
  directory: string;
  people: number;
  people_with_mobile: number;
  people_with_whatsapp: number;
  people_with_email: number;
  companies_with_number: number;
}

/** Licensed directories TECOMSA uses; any other name can be typed. Their sites are never accessed: file upload only. */
const DIRECTORIES = ["5INDEX", "Yelleb", "Infobel", "Kompass", "IFP"];

const FIELD_LABEL: Record<string, string> = {
  company: "Company", person: "Person", first_name: "First name", last_name: "Last name", title: "Title",
  phone: "Phone (company line)", mobile: "Mobile", whatsapp: "WhatsApp", email: "E-mail", website: "Website",
  sector: "Sector", city: "City", address: "Address", country: "Country", registration_number: "Registration no.",
  record_id: "Record ID",
};

function Chip({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "warning" }) {
  return (
    <span className={tone === "warning" ? "rounded bg-warning-soft px-1.5 py-0.5 text-[12px] text-warning" : "rounded bg-surface-muted px-1.5 py-0.5 text-[12px] ring-1 ring-inset ring-border"}>
      {children}
    </span>
  );
}

/** "12 mobiles" style tag for the history table; zero counts are left out. */
function Added({ icon: Icon, value, label, strong }: { icon: LucideIcon; value: number; label: string; strong?: boolean }) {
  if (!value) return null;
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px]", strong ? "bg-accent-soft text-accent" : "bg-surface-muted text-fg-muted")}>
      <Icon className="h-3 w-3" aria-hidden />
      <span className="font-medium tabular">{value.toLocaleString()}</span> {label}
    </span>
  );
}

function metrics(s: Summary) {
  return [
    { label: "New companies", value: s.companies_new, icon: Building2 },
    { label: "Existing companies", value: s.companies_existing, icon: Building2 },
    { label: "People", value: s.people, icon: UserRound, hint: `${s.people_new} new` },
    { label: "Mobiles", value: s.mobiles, icon: Smartphone },
    { label: "WhatsApp", value: s.whatsapp ?? 0, icon: MessageCircle },
    { label: "Other numbers", value: s.phones, icon: Phone },
    { label: "E-mails", value: s.emails, icon: Mail },
    { label: "Rows skipped", value: s.rows_skipped, icon: XCircle, hint: `of ${s.rows}` },
  ];
}

function ImportCenter() {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [directory, setDirectory] = useState("5INDEX");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<ImportRow | null>(null);
  const [dragging, setDragging] = useState(false);
  const custom = !DIRECTORIES.includes(directory);
  const canUpload = !busy && directory.trim() !== "";

  function pickDirectory(d: string) {
    setDirectory(d);
    setPreview(null);
    if (input.current) input.current.value = "";
  }
  const history = useApi<ImportRow[]>("/imports/directory");
  const coverage = useApi<Coverage[]>("/imports/directory/coverage");

  function upload(f: File, confirm: boolean) {
    const form = new FormData();
    form.append("file", f);
    form.append("directory", directory);
    if (confirm) form.append("confirm", "true");
    return api<Preview>(confirm ? "/imports/directory" : "/imports/directory/preview", { form });
  }

  async function choose(f: File | undefined) {
    if (!f) return;
    setFile(f);
    setPreview(null);
    setError(null);
    setBusy(true);
    try {
      setPreview(await upload(f, false));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The file could not be checked.");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!file) return;
    setBusy(true);
    try {
      const done = await upload(file, true);
      toast.success(`${done.file} imported: ${done.summary.companies_new} new companies, ${done.summary.mobiles} mobiles`);
      await coverage.reload();
      setFile(null);
      setPreview(null);
      if (input.current) input.current.value = "";
      await history.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The import failed.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(row: ImportRow) {
    setBusy(true);
    try {
      await api(`/imports/directory/${row.import_id}`, { method: "DELETE" });
      toast.success(`${row.file ?? "Import"} removed`);
      await Promise.all([history.reload(), coverage.reload()]);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not remove the import.");
    } finally {
      setBusy(false);
      setRemoving(null);
    }
  }

  return (
    <div className="space-y-6">
      <Section title="Upload a directory export" description="Nothing is written until you confirm.">
        <div className="space-y-4">
          <div>
            <p className="mb-1.5 text-xs font-medium text-fg">1 · Which directory is it from?</p>
            <div className="flex flex-wrap items-center gap-2">
              <FilterPills label="Directory" options={DIRECTORIES.map((d) => ({ value: d, label: d }))} value={directory} onChange={pickDirectory} />
              <span className="text-xs text-fg-subtle">or</span>
              <Input
                aria-label="Other directory"
                placeholder="Other…"
                value={custom ? directory : ""}
                maxLength={60}
                className={clsx("w-36", custom && directory && "border-accent")}
                disabled={busy}
                onChange={(e) => pickDirectory(e.target.value)}
              />
            </div>
          </div>

          <div>
            <p className="mb-1.5 text-xs font-medium text-fg">2 · Drop the export</p>
            <label
              onDragOver={(e) => {
                e.preventDefault();
                if (canUpload) setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                if (canUpload) void choose(e.dataTransfer.files[0]);
              }}
              className={clsx(
                "relative flex flex-col items-center justify-center gap-2 overflow-hidden rounded-lg border-2 border-dashed px-4 py-7 text-center transition-[border-color,background-color,transform] duration-200",
                !canUpload ? "cursor-not-allowed border-border opacity-70" : "cursor-pointer",
                dragging ? "scale-[1.01] border-accent bg-accent-soft/60" : canUpload && "border-border-strong hover:border-accent/50 hover:bg-surface-hover/60",
              )}
            >
              <input
                ref={input}
                type="file"
                accept=".xlsx,.xls,.csv"
                className="sr-only"
                onChange={(e) => void choose(e.target.files?.[0])}
                disabled={!canUpload}
                aria-label="Directory export file"
              />
              <span className={clsx("flex h-11 w-11 items-center justify-center rounded-full transition-[transform,background-color,color] duration-200", dragging ? "-translate-y-1 bg-accent text-white" : "bg-accent-soft text-accent")}>
                {busy && !preview ? <FileSpreadsheet className="h-5 w-5 animate-pulse" aria-hidden /> : <Upload className="h-5 w-5" aria-hidden />}
              </span>
              <span className="text-[13.5px] font-medium">
                {busy && !preview ? `Reading ${file?.name ?? "the file"}…` : dragging ? "Drop to check it" : (
                  <>
                    Drop a file here or <span className="text-accent underline-offset-2 hover:underline">browse</span>
                  </>
                )}
              </span>
              <span className="text-xs text-fg-muted">Excel (.xlsx, .xls) or CSV, up to 10 MB · bigger files: the command line (OPERATIONS.md)</span>
              {busy && !preview && <span className="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden"><span className="block h-full w-1/3 bg-accent" style={{ animation: "loading-bar 1.2s ease-in-out infinite" }} /></span>}
            </label>
          </div>
        </div>
        {error && <div className="mt-3"><Alert>{error}</Alert></div>}
        {preview && (
          <div className="mt-5 animate-page-in space-y-4 border-t border-border pt-5">
            <div className="flex flex-wrap items-center gap-2 text-[13px]">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-success/10 text-success">
                <FileSpreadsheet className="h-4 w-4" aria-hidden />
              </span>
              <span className="font-medium">{preview.file}</span>
              <Badge tone="info">{directory}</Badge>
              <span className="text-fg-muted">· {preview.summary.rows.toLocaleString()} rows read</span>
            </div>
            <div>
              <p className="mb-1.5 text-xs font-medium text-fg-muted">Columns detected</p>
              <ul className="stagger grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(preview.columns.detected).map(([field, header]) => (
                  <li key={field} className="flex items-center gap-2 rounded-md border border-border bg-surface px-2.5 py-1.5 text-[12.5px]">
                    <span className="truncate font-mono text-fg-muted" title={header}>{header}</span>
                    <ArrowRight className="h-3 w-3 shrink-0 text-accent" aria-hidden />
                    <span className="truncate font-medium">{FIELD_LABEL[field] ?? field}</span>
                  </li>
                ))}
              </ul>
              {preview.columns.ignored.length > 0 && (
                <p className="mt-2 flex flex-wrap items-center gap-1 text-[12.5px] text-fg-muted">Ignored: {preview.columns.ignored.map((h) => <Chip key={h}>{h}</Chip>)}</p>
              )}
              {preview.columns.unrecognised.length > 0 && (
                <p className="mt-2 flex flex-wrap items-center gap-1 text-[12.5px] text-fg-muted">
                  Not recognised (not imported): {preview.columns.unrecognised.map((h) => <Chip key={h} tone="warning">{h}</Chip>)}
                </p>
              )}
            </div>
            <MetricStrip items={metrics(preview.summary)} />
            {preview.review.length > 0 && (
              <details className="group rounded-lg border border-border">
                <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-[13px] font-medium transition-colors hover:text-accent [&::-webkit-details-marker]:hidden">
                  <ChevronDown className="h-4 w-4 text-fg-subtle transition-transform duration-200 group-open:rotate-180" aria-hidden />
                  Rows to review ({preview.review.length}{preview.review.length >= 100 ? "+" : ""})
                </summary>
                <ul className="max-h-64 divide-y divide-border overflow-y-auto text-[12.5px]">
                  {preview.review.map((r, i) => (
                    <li key={i} className="px-3 py-1.5">
                      <span className="text-fg-subtle">Row {r.line}</span> · {r.company}{r.person ? ` · ${r.person}` : ""} — <span className="text-fg-muted">{r.reason}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void confirm()} loading={busy} disabled={preview.summary.rows === preview.summary.rows_skipped}>
                <Upload className="h-3.5 w-3.5" aria-hidden /> Import {(preview.summary.rows - preview.summary.rows_skipped).toLocaleString()} rows
              </Button>
              <Button variant="secondary" onClick={() => input.current?.click()} disabled={busy}>Choose another file</Button>
            </div>
          </div>
        )}
      </Section>

      <Section title="Import history" description="Removing an import deletes what only it added (contacts, people, the companies it created); what other sources also state stays." flush>
        <DataTable
          caption="Directory imports"
          rows={history.data ?? undefined}
          loading={history.loading}
          error={history.error?.message}
          onRetry={history.reload}
          rowKey={(r) => r.import_id}
          empty={<EmptyState title="No directory file imported yet" />}
          columns={[
            { key: "at", header: "Imported", cell: (r) => <span className="text-fg-muted"><TimeAgo value={r.created_at} /></span> },
            {
              key: "file",
              header: "File",
              cell: (r) => (
                <span className={clsx("flex items-center gap-2.5", r.removed_at && "opacity-60")}>
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-success/10 text-success">
                    <FileSpreadsheet className="h-4 w-4" aria-hidden />
                  </span>
                  <span className="min-w-0 leading-tight">
                    <span className={clsx("block truncate font-medium", r.removed_at && "line-through")}>{r.file ?? "—"}</span>
                    <span className="text-xs text-fg-muted">{r.directory ?? "—"} · {r.user ?? "Command line"}</span>
                  </span>
                </span>
              ),
            },
            {
              key: "summary",
              header: "Added",
              className: "whitespace-normal",
              cell: (r) => (
                <span className="flex max-w-[460px] flex-wrap gap-1">
                  <Added icon={Building2} value={r.summary.companies_new} label="new companies" strong />
                  <Added icon={UserRound} value={r.summary.people} label="people" />
                  <Added icon={Smartphone} value={r.summary.mobiles} label="mobiles" strong />
                  <Added icon={MessageCircle} value={r.summary.whatsapp ?? 0} label="WhatsApp" />
                  <Added icon={Phone} value={r.summary.phones} label="numbers" />
                  <Added icon={Mail} value={r.summary.emails} label="e-mails" />
                </span>
              ),
            },
            { key: "status", header: "Status", cell: (r) => (r.removed_at ? <Badge tone="neutral" dot>Removed</Badge> : <Badge tone="success" dot>Imported</Badge>) },
            {
              key: "actions",
              header: <span className="sr-only">Actions</span>,
              align: "right",
              cell: (r) =>
                !r.removed_at && (
                  <Button variant="danger" size="sm" className="opacity-50 transition-opacity focus-visible:opacity-100 group-hover:opacity-100" onClick={() => setRemoving(r)}>
                    Remove
                  </Button>
                ),
            },
          ]}
        />
      </Section>
      <Section title="Coverage per directory" description="What each directory states today (also when another source states it too): which one brings decision-makers' mobiles." flush>
        <DataTable
          caption="Coverage per directory"
          rows={coverage.data ?? undefined}
          loading={coverage.loading}
          error={coverage.error?.message}
          onRetry={coverage.reload}
          rowKey={(c) => c.directory}
          empty={<EmptyState title="Nothing imported yet" />}
          columns={[
            { key: "directory", header: "Directory", cell: (c) => <span className="font-medium">{c.directory}</span> },
            { key: "people", header: "People", align: "right", cell: (c) => <span className="font-medium tabular">{c.people.toLocaleString()}</span> },
            { key: "mobile", header: "With a mobile", cell: (c) => <Meter value={c.people_with_mobile} max={c.people} /> },
            { key: "whatsapp", header: "With WhatsApp", cell: (c) => <Meter value={c.people_with_whatsapp} max={c.people} /> },
            { key: "email", header: "With an e-mail", cell: (c) => <Meter value={c.people_with_email} max={c.people} /> },
            { key: "companies", header: "Companies with a number", align: "right", cell: (c) => <span className="tabular">{c.companies_with_number.toLocaleString()}</span> },
          ]}
        />
      </Section>
      <ConfirmDialog
        open={removing !== null}
        title={`Remove ${removing?.file ?? "this import"}?`}
        confirmLabel="Remove import"
        tone="danger"
        busy={busy}
        onConfirm={() => removing && void remove(removing)}
        onClose={() => setRemoving(null)}
      >
        The contacts, people and companies only this import added are deleted. Companies and contacts other sources (or another import) also state are kept. The file can be imported again later.
      </ConfirmDialog>
    </div>
  );
}

export default function ImportsPage() {
  return (
    <RequireCapability capability="run_imports">
      <PageHeader
        title="Directory imports"
        description="Companies, decision-makers and their mobiles from the exports of TECOMSA's licensed directories. Columns are detected automatically, in English or French."
      />
      <p className="-mt-2 mb-5 inline-flex items-center gap-1.5 rounded-full bg-surface-muted px-3 py-1 text-xs text-fg-muted">
        <ShieldCheck className="h-3.5 w-3.5 text-success" aria-hidden /> File upload only: the directories&apos; websites are never accessed.
      </p>
      <ImportCenter />
    </RequireCapability>
  );
}
