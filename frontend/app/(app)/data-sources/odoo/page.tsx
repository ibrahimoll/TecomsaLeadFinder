"use client";

import { ArrowRight, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { FileDrop } from "@/components/file-drop";
import { RequireCapability } from "@/components/guard";
import { ImportStatusBadge } from "@/components/status-badges";
import { Alert, Button, ButtonLink, DataTable, EmptyState, PageHeader, RowLink, Section } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { IMPORT_TYPE_LABEL } from "@/lib/constants";
import { formatDateTime } from "@/lib/format";
import type { ImportPreview, ImportRun, ImportType, Page } from "@/types";

const PANELS: { type: ImportType; title: string; description: string; columns: string }[] = [
  {
    type: "ODOO_CRM",
    title: "CRM leads & opportunities",
    description: "Odoo → CRM → Pipeline (list view) → select all → Export. Include archived and lost records.",
    columns: "Opportunity, Customer, Contact Name, Email, Phone, Salesperson, Sales Team, Stage, Type, Expected Revenue, Active, Lost Reason, Created on",
  },
  {
    type: "ODOO_CONTACTS",
    title: "Contacts & companies",
    description: "Odoo → Contacts (list view) → select all → Export. Include both companies and individuals.",
    columns: "Name, Is a Company, Related Company, Website, Email, Phone, Mobile, Street, City, Country, Salesperson",
  },
];

function UploadPanel({ type, title, description, columns }: (typeof PANELS)[number]) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function upload() {
    if (!file) return;
    setUploading(true);
    setError(null);
    const form = new FormData();
    form.set("import_type", type);
    form.set("file", file);
    try {
      const preview = await api<ImportPreview>("/imports", { form });
      router.push(`/imports/${preview.run.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
      setUploading(false);
    }
  }

  return (
    <Section title={title} description={description}>
      <div className="space-y-3">
        <FileDrop
          file={file}
          disabled={uploading}
          onFile={(f, message) => {
            setFile(f);
            setError(message ?? null);
          }}
        />
        {error && <Alert>{error}</Alert>}
        <details className="text-xs text-fg-muted">
          <summary className="cursor-pointer select-none hover:text-fg">Columns LeadFinder recognises automatically</summary>
          <p className="mt-1.5 leading-relaxed">{columns}. Other column names can be mapped in the next step.</p>
        </details>
        <div className="flex justify-end">
          <Button onClick={upload} disabled={!file || uploading}>
            {uploading ? "Reading file…" : "Upload & preview"} <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </Button>
        </div>
      </div>
    </Section>
  );
}

function RecentImports() {
  const { data, error, loading, reload } = useApi<Page<ImportRun>>("/imports", { page_size: 8 });
  return (
    <Section title="Recent imports" flush actions={<ButtonLink href="/imports" variant="ghost" size="sm">Full history</ButtonLink>}>
      <DataTable
        caption="Recent imports"
        rows={data?.items}
        loading={loading}
        error={error?.message}
        onRetry={reload}
        rowKey={(r) => r.id}
        empty={<EmptyState compact title="No imports yet" description="Upload the CRM export first, then contacts." />}
        columns={[
          { key: "file", header: "File", cell: (r) => <RowLink href={`/imports/${r.id}`}>{r.original_filename}</RowLink> },
          { key: "type", header: "Type", cell: (r) => IMPORT_TYPE_LABEL[r.import_type] },
          { key: "rows", header: "Rows", align: "right", cell: (r) => r.row_count.toLocaleString() },
          { key: "status", header: "Status", cell: (r) => <ImportStatusBadge status={r.status} /> },
          { key: "by", header: "By", cell: (r) => <span className="text-fg-muted">{r.creator?.name ?? "—"}</span> },
          { key: "at", header: "Uploaded", cell: (r) => <span className="text-fg-muted">{formatDateTime(r.created_at)}</span> },
        ]}
      />
    </Section>
  );
}

export default function OdooImportsPage() {
  return (
    <RequireCapability capability="run_imports">
      <PageHeader
        breadcrumbs={[{ label: "Data sources" }, { label: "Odoo" }]}
        title="Odoo imports"
        description="Import TECOMSA's Odoo exports so LeadFinder never treats an existing relationship as a new prospect."
      />
      <div className="mb-5 flex gap-3 rounded-lg border border-border bg-surface px-4 py-3 text-[13px]">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-fg-muted" aria-hidden />
        <p className="text-fg-muted">
          <span className="font-medium text-fg">Odoo is the source of truth for existing relationships.</span> Each upload is parsed and
          previewed first. Nothing is saved until you confirm. Re-importing a newer export updates existing records instead of
          duplicating them. The uploaded file is kept only as a record of the import source.
        </p>
      </div>
      <div className="mb-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
        {PANELS.map((p) => (
          <UploadPanel key={p.type} {...p} />
        ))}
      </div>
      <RecentImports />
    </RequireCapability>
  );
}
