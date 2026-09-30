"use client";

import clsx from "clsx";
import { Check, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert, Button, Field, Input, Section, Select, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import {
  CAMPAIGN_SIZE_RANGES,
  countryNames,
  DIVISIONS,
  INDUSTRIES,
  ROLE_SUGGESTIONS,
  TARGET_COUNTS,
} from "@/lib/constants";
import type { Campaign, Division } from "@/types";

const CUSTOM = "__custom__";

interface Values {
  name: string;
  tecomsa_division: Division | "";
  country: string;
  region: string;
  city: string;
  industry: string;
  size: string;
  target_roles: string[];
  target_company_count: string;
  max_lusha_credit_budget: string;
  additional_instructions: string;
}

function sizeKey(min: number | null, max: number | null) {
  return `${min ?? ""}-${max ?? ""}`;
}

function initialValues(c?: Campaign): Values {
  return {
    name: c?.name ?? "",
    tecomsa_division: c?.tecomsa_division ?? "",
    country: c?.country ?? "Lebanon",
    region: c?.region ?? "",
    city: c?.city ?? "",
    industry: c?.industry ?? "",
    size: sizeKey(c?.company_size_min ?? null, c?.company_size_max ?? null),
    target_roles: c?.target_roles ?? [],
    target_company_count: String(c?.target_company_count ?? 20),
    max_lusha_credit_budget: c?.max_lusha_credit_budget != null ? String(c.max_lusha_credit_budget) : "",
    additional_instructions: c?.additional_instructions ?? "",
  };
}

function RolePicker({
  division,
  selected,
  onChange,
}: {
  division: Division | "";
  selected: string[];
  onChange: (roles: string[]) => void;
}) {
  const [custom, setCustom] = useState("");
  const suggestions = division ? ROLE_SUGGESTIONS[division] : [];
  const options = [...suggestions, ...selected.filter((r) => !suggestions.includes(r))];

  const toggle = (role: string) =>
    onChange(selected.includes(role) ? selected.filter((r) => r !== role) : [...selected, role]);

  function addCustom() {
    const role = custom.trim();
    if (role && !selected.some((r) => r.toLowerCase() === role.toLowerCase())) onChange([...selected, role]);
    setCustom("");
  }

  return (
    <div>
      {options.length === 0 && <p className="mb-2 text-xs text-fg-muted">Choose a division to see suggested roles.</p>}
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Target roles">
        {options.map((role) => {
          const active = selected.includes(role);
          return (
            <button
              type="button"
              key={role}
              onClick={() => toggle(role)}
              aria-pressed={active}
              className={clsx(
                "inline-flex h-7 items-center gap-1 rounded border px-2.5 text-xs font-medium transition-colors",
                active ? "border-fg bg-fg text-white" : "border-border-strong bg-surface text-fg hover:bg-surface-hover",
              )}
            >
              {active && <Check className="h-3 w-3" aria-hidden />}
              {role}
            </button>
          );
        })}
      </div>
      <div className="mt-2 flex max-w-sm gap-2">
        <Input
          aria-label="Add another role"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addCustom();
            }
          }}
          placeholder="Add another role"
          maxLength={100}
        />
        <Button variant="secondary" onClick={addCustom} disabled={!custom.trim()}>
          <Plus className="h-3.5 w-3.5" aria-hidden /> Add
        </Button>
      </div>
    </div>
  );
}

export function CampaignForm({ campaign }: { campaign?: Campaign }) {
  const router = useRouter();
  const [values, setValues] = useState<Values>(() => initialValues(campaign));
  const [industryMode, setIndustryMode] = useState<"list" | "custom">(
    campaign?.industry && !INDUSTRIES.includes(campaign.industry) ? "custom" : "list",
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (field: keyof Values) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [field]: e.target.value }));

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setErrors({});
    setFormError(null);
    const range = CAMPAIGN_SIZE_RANGES.find((r) => sizeKey(r.min, r.max) === values.size);
    const body = {
      name: values.name,
      tecomsa_division: values.tecomsa_division,
      country: values.country,
      region: values.region,
      city: values.city,
      industry: values.industry,
      company_size_min: range?.min ?? null,
      company_size_max: range?.max ?? null,
      target_roles: values.target_roles,
      target_company_count: Number(values.target_company_count),
      max_lusha_credit_budget: values.max_lusha_credit_budget === "" ? null : Number(values.max_lusha_credit_budget),
      additional_instructions: values.additional_instructions,
    };
    try {
      const saved = campaign
        ? await api<Campaign>(`/campaigns/${campaign.id}`, { method: "PATCH", body })
        : await api<Campaign>("/campaigns", { method: "POST", body });
      router.push(`/campaigns/${saved.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors);
        setFormError(err.message);
      }
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {formError && <Alert>{formError}</Alert>}

      <Section title="Campaign">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Field label="Campaign name" htmlFor="name" required error={errors.name} className="md:col-span-2">
            <Input id="name" value={values.name} onChange={set("name")} required maxLength={200} placeholder="e.g. Frinzo – Beirut restaurants" />
          </Field>
          <Field label="TECOMSA division" htmlFor="division" required error={errors.tecomsa_division}>
            <Select id="division" value={values.tecomsa_division} onChange={set("tecomsa_division")} required>
              <option value="">Select division</option>
              {DIVISIONS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </Section>

      <Section title="Target market">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Field label="Country" htmlFor="country" required error={errors.country}>
            <Select id="country" value={values.country} onChange={set("country")} required>
              <option value="">Select country</option>
              {countryNames().map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Region" htmlFor="region" error={errors.region}>
            <Input id="region" value={values.region} onChange={set("region")} maxLength={100} placeholder="Optional, e.g. Mount Lebanon" />
          </Field>
          <Field label="City" htmlFor="city" error={errors.city}>
            <Input id="city" value={values.city} onChange={set("city")} maxLength={100} placeholder="Optional" />
          </Field>
        </div>
      </Section>

      <Section title="Company criteria">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Field label="Industry" htmlFor="industry" error={errors.industry}>
            {industryMode === "list" ? (
              <Select
                id="industry"
                value={values.industry}
                onChange={(e) => {
                  if (e.target.value === CUSTOM) {
                    setIndustryMode("custom");
                    setValues((v) => ({ ...v, industry: "" }));
                  } else set("industry")(e);
                }}
              >
                <option value="">Any industry</option>
                {INDUSTRIES.map((i) => (
                  <option key={i} value={i}>
                    {i}
                  </option>
                ))}
                <option value={CUSTOM}>Other (type your own)…</option>
              </Select>
            ) : (
              <div className="flex gap-2">
                <Input id="industry" value={values.industry} onChange={set("industry")} maxLength={150} placeholder="Custom industry" autoFocus />
                <Button variant="ghost" onClick={() => setIndustryMode("list")}>
                  List
                </Button>
              </div>
            )}
          </Field>
          <Field label="Company size" htmlFor="size" error={errors.company_size_min ?? errors.company_size_max}>
            <Select id="size" value={values.size} onChange={set("size")}>
              {CAMPAIGN_SIZE_RANGES.map((r) => (
                <option key={r.label} value={sizeKey(r.min, r.max)}>
                  {r.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Target company count" htmlFor="count" required error={errors.target_company_count}>
            <Input
              id="count"
              type="number"
              min={1}
              max={10000}
              list="count-options"
              value={values.target_company_count}
              onChange={set("target_company_count")}
              required
            />
            <datalist id="count-options">
              {TARGET_COUNTS.map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
          </Field>
        </div>
      </Section>

      <Section title="Decision-makers" description="Roles to look for at qualifying companies.">
        <Field label="Target roles" error={errors.target_roles}>
          <RolePicker
            division={values.tecomsa_division}
            selected={values.target_roles}
            onChange={(roles) => setValues((v) => ({ ...v, target_roles: roles }))}
          />
        </Field>
      </Section>

      <Section title="Budget & notes">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Field
            label="Max. Lusha credit budget"
            htmlFor="budget"
            error={errors.max_lusha_credit_budget}
            hint="Stored for later phases. No credits are used now."
          >
            <Input id="budget" type="number" min={0} value={values.max_lusha_credit_budget} onChange={set("max_lusha_credit_budget")} placeholder="Optional" />
          </Field>
          <Field label="Additional instructions" htmlFor="instructions" error={errors.additional_instructions} className="md:col-span-2">
            <Textarea id="instructions" value={values.additional_instructions} onChange={set("additional_instructions")} maxLength={5000} />
          </Field>
        </div>
      </Section>

      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={() => router.back()}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : campaign ? "Save changes" : "Save as draft"}
        </Button>
      </div>
    </form>
  );
}
