"use client";

import { ChevronRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { FileDrop } from "@/components/file-drop";
import { RequireCapability } from "@/components/guard";
import { ImportsTable } from "@/components/import-table";
import { Alert, ButtonLink, EmptyState, PageHeader, Section } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import type { ImportPreview, ImportRun, ImportType, Page } from "@/types";

const RECENT = 10;

const PANELS: { type: ImportType; title: string; howTo: string; detects: string; step: number; hint: string }[] = [
  {
    type: "ODOO_CONTACTS",
    title: "Odoo contacts",
    howTo: "Odoo → Contacts → list view → select all → Export (XLSX or CSV).",
    detects: "Company Name, Contact Name, Job Position, Phone / Mobile, Email, Country, City, Website, Address",
    step: 1,
    hint: "Start here",
  },
  {
    type: "ODOO_CRM",
    title: "Odoo CRM leads & opportunities",
    howTo: "Odoo → CRM → Pipeline → list view → select all, including archived and lost → Export.",
    detects: "Opportunity, Customer, Contact, Email, Phone, Salesperson, Stage, Type, Revenue, Lost Reason, Dates",
    step: 2,
    hint: "Then the pipeline",
  },
];

function UploadPanel({ type, title, howTo, detects, step, hint }: (typeof PANELS)[number]) {
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

  // "Odoo → CRM → Pipeline → …" as a click path; the last part ("select all … → Export") stays readable.
  const path = howTo.replace(/\.$/, "").split(" → ");
  return (
    <section className="flex flex-col rounded-lg border border-border bg-surface shadow-card">
      <div className="flex items-start gap-3 border-b border-border px-4 py-4">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent text-[12px] font-semibold text-white" aria-hidden>
          {step}
        </span>
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">{hint}</p>
          <h2 className="text-[15px] font-semibold">{title}</h2>
          <ol className="mt-1.5 flex flex-wrap items-center gap-1 text-[11.5px] text-fg-muted" aria-label="Where to export it in Odoo">
            {path.map((part, i) => (
              <li key={part} className="flex items-center gap-1">
                {i > 0 && <ChevronRight className="h-3 w-3 text-fg-subtle" aria-hidden />}
                <span className="rounded bg-surface-muted px-1.5 py-0.5 ring-1 ring-inset ring-border">{part}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
      <div className="flex-1 space-y-3 p-4">
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
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-fg-subtle">Columns detected automatically</p>
          <p className="mt-0.5 text-[11.5px] text-fg-muted">Any practical layout: headers anywhere or none, title and note rows, several sheets, combined cells.</p>
          <ul className="stagger mt-1.5 flex flex-wrap gap-1">
            {detects.split(", ").map((col) => (
              <li key={col} className="rounded-full border border-border px-2 py-0.5 text-[11px] text-fg-muted">
                {col}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
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
      <div className="stagger mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
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
