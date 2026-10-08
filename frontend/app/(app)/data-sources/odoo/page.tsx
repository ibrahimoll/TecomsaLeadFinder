"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { FileDrop } from "@/components/file-drop";
import { RequireCapability } from "@/components/guard";
import { ImportsTable } from "@/components/import-table";
import { Alert, ButtonLink, EmptyState, PageHeader, Section } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import type { ImportPreview, ImportRun, ImportType, Page } from "@/types";

const RECENT = 10;

const PANELS: { type: ImportType; title: string; howTo: string; detects: string }[] = [
  {
    type: "ODOO_CONTACTS",
    title: "Odoo contacts",
    howTo: "Odoo → Contacts → list view → select all → Export (XLSX or CSV).",
    detects: "Company Name, Contact Name, Job Position, Phone / Mobile, Email, Country, City",
  },
  {
    type: "ODOO_CRM",
    title: "Odoo CRM leads & opportunities",
    howTo: "Odoo → CRM → Pipeline → list view → select all, including archived and lost → Export.",
    detects: "Opportunity, Customer, Contact, Email, Phone, Salesperson, Stage, Type, Revenue, Lost Reason, Dates",
  },
];

function UploadPanel({ type, title, howTo, detects }: (typeof PANELS)[number]) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  // Choosing a file uploads it straight away; the next screen is the preview.
  async function upload(chosen: File) {
    setUploading(true);
    setError(null);
    const form = new FormData();
    form.set("import_type", type);
    form.set("file", chosen);
    try {
      const preview = await api<ImportPreview>("/imports", { form });
      router.push(`/imports/${preview.run.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The file could not be uploaded.");
      setFile(null);
      setUploading(false);
    }
  }

  return (
    <Section title={title} description={howTo}>
      <div className="space-y-3">
        <FileDrop
          file={file}
          busy={uploading}
          disabled={uploading}
          onFile={(f, message) => {
            setFile(f);
            setError(message ?? null);
            if (f) void upload(f);
          }}
        />
        {error && <Alert title="The file was not imported">{error}</Alert>}
        <p className="text-xs text-fg-muted">
          <span className="text-fg">Detected automatically:</span> {detects}.
        </p>
      </div>
    </Section>
  );
}

function OdooImports() {
  const { data, error, loading, reload } = useApi<Page<ImportRun>>("/imports", { page_size: RECENT });
  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Data sources" }, { label: "Odoo" }]}
        title="Odoo imports"
        description="Upload an Odoo export, check the preview, then import. Nothing is saved until you click Import records."
      />
      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {PANELS.map((p) => (
          <UploadPanel key={p.type} {...p} />
        ))}
      </div>
      <Section
        title="Imports"
        description="Delete an import to remove it from the history, with or without the records it brought in."
        flush
        actions={
          data && data.total > RECENT ? (
            <ButtonLink href="/imports" variant="ghost" size="sm">
              View all {data.total.toLocaleString()}
            </ButtonLink>
          ) : undefined
        }
      >
        <ImportsTable
          rows={data?.items}
          loading={loading}
          error={error?.message}
          onRetry={reload}
          onChanged={reload}
          empty={
            <EmptyState
              compact
              title="No Odoo files have been imported yet."
              description="Start with the contacts export above."
            />
          }
        />
      </Section>
    </>
  );
}

export default function OdooImportsPage() {
  return (
    <RequireCapability capability="run_imports">
      <OdooImports />
    </RequireCapability>
  );
}
