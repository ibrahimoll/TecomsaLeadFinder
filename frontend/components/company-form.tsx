"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, Input, Select, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { COMPANY_SIZES, countryNames, INDUSTRIES } from "@/lib/constants";
import type { Company } from "@/types";

const FIELDS = [
  "name",
  "website",
  "country",
  "city",
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

export function CompanyForm({ company }: { company?: Company }) {
  const router = useRouter();
  const [values, setValues] = useState<Values>(() => initialValues(company));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const industries = values.industry && !INDUSTRIES.includes(values.industry) ? [values.industry, ...INDUSTRIES] : INDUSTRIES;

  const set = (field: keyof Values) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [field]: e.target.value }));

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
    <form onSubmit={onSubmit}>
      <Card>
        <div className="space-y-4">
          {formError && <Alert>{formError}</Alert>}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field label="Company name" htmlFor="name" required error={errors.name} className="md:col-span-2">
              <Input id="name" value={values.name} onChange={set("name")} required maxLength={255} />
            </Field>
            <Field label="Website" htmlFor="website" error={errors.website} hint="e.g. example.com">
              <Input id="website" value={values.website} onChange={set("website")} maxLength={500} />
            </Field>
            <Field label="Industry" htmlFor="industry" error={errors.industry}>
              <Input id="industry" list="industry-options" value={values.industry} onChange={set("industry")} maxLength={150} placeholder="Select or type an industry" />
              <datalist id="industry-options">
                {industries.map((i) => (
                  <option key={i} value={i} />
                ))}
              </datalist>
            </Field>
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
            <Field label="Main phone" htmlFor="main_phone" error={errors.main_phone} hint="International format preferred, e.g. +961 1 234 567">
              <Input id="main_phone" value={values.main_phone} onChange={set("main_phone")} maxLength={50} />
            </Field>
            <Field label="Main email" htmlFor="main_email" error={errors.main_email}>
              <Input id="main_email" type="email" value={values.main_email} onChange={set("main_email")} maxLength={320} />
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
            <Field label="Description" htmlFor="description" error={errors.description} className="md:col-span-2">
              <Textarea id="description" value={values.description} onChange={set("description")} maxLength={5000} />
            </Field>
          </div>
          <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
            <Button type="button" variant="secondary" onClick={() => router.back()}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? "Saving…" : company ? "Save changes" : "Add company"}
            </Button>
          </div>
        </div>
      </Card>
    </form>
  );
}
