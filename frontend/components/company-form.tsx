"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { CrmStatusBadge } from "@/components/status-badges";
import { Alert, Button, Field, Input, RowLink, Section, Select, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { COMPANY_SIZES, countryNames, INDUSTRIES } from "@/lib/constants";
import type { Company, DuplicateCandidate } from "@/types";

const FIELDS = [
  "name",
  "website",
  "country",
  "city",
  "address",
  "industry",
  "main_phone",
  "main_email",
  "company_size",
  "description",
] as const;
type Values = Record<(typeof FIELDS)[number], string>;

function initialValues(company?: Company): Values {
  return Object.fromEntries(FIELDS.map((f) => [f, (company?.[f] as string | null) ?? ""])) as Values;
}

/** Live duplicate check against existing companies (deterministic matching on the server). */
function useDuplicates(values: Values, excludeId?: number) {
  const [matches, setMatches] = useState<DuplicateCandidate[]>([]);
  const { name, website, main_email, main_phone, city, country } = values;
  useEffect(() => {
    if (!name.trim() && !website.trim() && !main_email.trim() && !main_phone.trim()) {
      setMatches([]);
      return;
    }
    const timer = setTimeout(() => {
      api<DuplicateCandidate[]>("/companies/duplicates", {
        query: { name, website, email: main_email, phone: main_phone, city, country, exclude_id: excludeId },
      })
        .then(setMatches)
        .catch(() => setMatches([]));
    }, 400);
    return () => clearTimeout(timer);
  }, [name, website, main_email, main_phone, city, country, excludeId]);
  return matches;
}

export function CompanyForm({ company }: { company?: Company }) {
  const router = useRouter();
  const [values, setValues] = useState<Values>(() => initialValues(company));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const duplicates = useDuplicates(values, company?.id);
  const industries = values.industry && !INDUSTRIES.includes(values.industry) ? [values.industry, ...INDUSTRIES] : INDUSTRIES;

  const set = (field: keyof Values) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [field]: e.target.value }));
  const invalid = (field: string) => (errors[field] ? { "aria-invalid": true as const, "aria-describedby": `${field}-message` } : {});

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setErrors({});
    setFormError(null);
    try {
      const saved = company
        ? await api<Company>(`/companies/${company.id}`, { method: "PATCH", body: values })
        : await api<Company>("/companies", { method: "POST", body: values });
      router.push(`/companies/${saved.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors);
        setFormError(err.message);
      }
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      {formError && <Alert>{formError}</Alert>}

      {duplicates.length > 0 && (
        <Alert tone="warning" title="This may already exist">
          <ul className="mt-1 space-y-1">
            {duplicates.map((d) => (
              <li key={d.company.id} className="flex flex-wrap items-center gap-2">
                <RowLink href={`/companies/${d.company.id}`}>{d.company.name}</RowLink>
                <CrmStatusBadge status={d.company.odoo_status} />
                <span className="text-xs text-fg-muted">{d.reason}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-fg-muted">Open the existing record instead of creating a duplicate, unless this is a different organisation.</p>
        </Alert>
      )}

      <Section title="Company">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Company name" htmlFor="name" required error={errors.name} className="md:col-span-2">
            <Input id="name" value={values.name} onChange={set("name")} required maxLength={255} autoFocus={!company} {...invalid("name")} />
          </Field>
          <Field label="Website" htmlFor="website" error={errors.website} hint="Domain or URL, e.g. example.com">
            <Input id="website" value={values.website} onChange={set("website")} maxLength={500} {...invalid("website")} />
          </Field>
          <Field label="Industry" htmlFor="industry" error={errors.industry}>
            <Input id="industry" list="industry-options" value={values.industry} onChange={set("industry")} maxLength={150} placeholder="Select or type" />
            <datalist id="industry-options">
              {industries.map((i) => (
                <option key={i} value={i} />
              ))}
            </datalist>
          </Field>
          <Field label="Company size" htmlFor="company_size" error={errors.company_size}>
            <Select id="company_size" value={values.company_size} onChange={set("company_size")}>
              <option value="">Unknown</option>
              {COMPANY_SIZES.map((s) => (
                <option key={s} value={s}>
                  {s} employees
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </Section>

      <Section title="Location & contact">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Country" htmlFor="country" error={errors.country}>
            <Select id="country" value={values.country} onChange={set("country")}>
              <option value="">Select country</option>
              {countryNames().map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="City" htmlFor="city" error={errors.city}>
            <Input id="city" value={values.city} onChange={set("city")} maxLength={100} />
          </Field>
          <Field label="Address" htmlFor="address" error={errors.address} className="md:col-span-2">
            <Input id="address" value={values.address} onChange={set("address")} maxLength={500} />
          </Field>
          <Field label="Main phone" htmlFor="main_phone" error={errors.main_phone} hint="Local Lebanese numbers are normalised when the country is Lebanon">
            <Input id="main_phone" type="tel" value={values.main_phone} onChange={set("main_phone")} maxLength={50} {...invalid("main_phone")} />
          </Field>
          <Field label="Main email" htmlFor="main_email" error={errors.main_email}>
            <Input id="main_email" type="email" value={values.main_email} onChange={set("main_email")} maxLength={320} {...invalid("main_email")} />
          </Field>
        </div>
      </Section>

      <Section title="Notes">
        <Field label="Description" htmlFor="description" error={errors.description}>
          <Textarea id="description" value={values.description} onChange={set("description")} maxLength={5000} />
        </Field>
      </Section>

      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={() => router.back()}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : company ? "Save changes" : "Add company"}
        </Button>
      </div>
    </form>
  );
}
