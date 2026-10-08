"use client";

import clsx from "clsx";
import { Briefcase, Building2, Check, Circle, Crosshair, MapPin, Plus, Users, X, type LucideIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";

import { Alert, Button, Field, Input, Select, Textarea } from "@/components/ui";
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

const DIVISION_HINT: Record<Division, string> = {
  FRINZO: "WhatsApp & Instagram automation",
  ODOO: "ERP implementation",
  IT: "Infrastructure & IT services",
};

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

/** Selectable chip used for single- and multi-choice filters. */
function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={clsx(
        "inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[12.5px] font-medium transition-[background-color,border-color,color] active:translate-y-px",
        active
          ? "border-ink bg-ink text-white"
          : "border-border-strong bg-surface text-fg-muted shadow-[0_1px_0_rgb(17_17_20/0.03)] hover:border-fg-subtle/70 hover:text-fg",
      )}
    >
      {active && <Check className="h-3 w-3" aria-hidden />}
      {children}
    </button>
  );
}

/** One filter group: label + explanation on the left, controls on the right (settings-page rhythm). */
function Group({ icon: Icon, title, hint, children }: { icon: LucideIcon; title: string; hint: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-3 border-b border-border px-5 py-5 last:border-b-0 md:grid-cols-[200px_minmax(0,1fr)] md:gap-8">
      <div>
        <p className="flex items-center gap-2 text-[13px] font-semibold text-fg">
          <Icon className="h-4 w-4 text-fg-subtle" strokeWidth={1.75} aria-hidden />
          {title}
        </p>
        <p className="mt-1 text-[12.5px] leading-[18px] text-fg-muted">{hint}</p>
      </div>
      <div className="min-w-0 space-y-4">{children}</div>
    </div>
  );
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
  const toggle = (role: string) => onChange(selected.includes(role) ? selected.filter((r) => r !== role) : [...selected, role]);

  function addCustom() {
    const role = custom.trim();
    if (role && !selected.some((r) => r.toLowerCase() === role.toLowerCase())) onChange([...selected, role]);
    setCustom("");
  }

  return (
    <div>
      {options.length === 0 && <p className="mb-2 text-[12.5px] text-fg-subtle">Choose a division to see suggested roles, or type your own.</p>}
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Target roles">
        {options.map((role) => (
          <Chip key={role} active={selected.includes(role)} onClick={() => toggle(role)}>
            {role}
          </Chip>
        ))}
      </div>
      <div className="mt-2.5 flex max-w-sm gap-2">
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
          placeholder="Add a job title, e.g. Head of Operations"
          maxLength={100}
        />
        <Button variant="secondary" onClick={addCustom} disabled={!custom.trim()}>
          <Plus className="h-3.5 w-3.5" aria-hidden /> Add
        </Button>
      </div>
    </div>
  );
}

/** Live, plain-language description of the search being defined. */
function SearchBrief({ values }: { values: Values }) {
  const size = CAMPAIGN_SIZE_RANGES.find((r) => sizeKey(r.min, r.max) === values.size);
  const where = [values.city, values.region, values.country].filter(Boolean).join(", ") || "any country";
  const checks = [
    { label: "Name and division", done: Boolean(values.name.trim() && values.tecomsa_division) },
    { label: "Market", done: Boolean(values.country) },
    { label: "Industry", done: Boolean(values.industry) },
    { label: "Decision-makers", done: values.target_roles.length > 0 },
  ];
  const strong = (text: string) => <span className="font-medium text-fg">{text}</span>;
  return (
    <div className="rounded-lg border border-border bg-surface shadow-[0_1px_0_rgb(17_17_20/0.03)]">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <Crosshair className="h-4 w-4 text-accent" strokeWidth={1.75} aria-hidden />
        <p className="text-[13px] font-semibold">Search brief</p>
      </div>
      <p className="px-4 py-3 text-[13px] leading-[21px] text-fg-muted">
        Find {strong(`${Number(values.target_company_count) || 0} ${values.industry || "companies of any industry"}`)}
        {values.industry ? " companies" : ""} in {strong(where)}
        {size && size.min !== null ? <> with {strong(size.label)}</> : null}
        {values.target_roles.length > 0 ? (
          <>
            , and reach {strong(values.target_roles.slice(0, 3).join(", "))}
            {values.target_roles.length > 3 ? ` +${values.target_roles.length - 3} more` : ""}
          </>
        ) : null}
        .
      </p>
      <ul className="space-y-1.5 border-t border-border px-4 py-3">
        {checks.map((c) => (
          <li key={c.label} className="flex items-center gap-2 text-[12.5px]">
            {c.done ? (
              <Check className="h-3.5 w-3.5 text-success" aria-hidden />
            ) : (
              <Circle className="h-3.5 w-3.5 text-border-strong" aria-hidden />
            )}
            <span className={c.done ? "text-fg" : "text-fg-muted"}>{c.label}</span>
          </li>
        ))}
      </ul>
      <p className="border-t border-border px-4 py-2.5 text-[11.5px] leading-4 text-fg-subtle">
        Companies already known in Odoo are protected and never treated as new prospects.
      </p>
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

  const set = (field: keyof Values) => (e: { target: { value: string } }) => setValues((v) => ({ ...v, [field]: e.target.value }));
  const setValue = (field: keyof Values, value: string) => setValues((v) => ({ ...v, [field]: value }));

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
    <form onSubmit={onSubmit} className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="min-w-0 space-y-4">
        {formError && <Alert>{formError}</Alert>}

        <div className="rounded-lg border border-border bg-surface shadow-[0_1px_0_rgb(17_17_20/0.03)]">
          <Group icon={Briefcase} title="Campaign" hint="What this search is for and which TECOMSA offer it supports.">
            <Field label="Campaign name" htmlFor="name" required error={errors.name}>
              <Input id="name" value={values.name} onChange={set("name")} required maxLength={200} placeholder="e.g. Frinzo · Beirut restaurants" />
            </Field>
            <Field label="TECOMSA division" required error={errors.tecomsa_division}>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3" role="radiogroup" aria-label="TECOMSA division">
                {DIVISIONS.map((d) => {
                  const active = values.tecomsa_division === d.value;
                  return (
                    <button
                      key={d.value}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      onClick={() => setValue("tecomsa_division", d.value)}
                      className={clsx(
                        "rounded-md border px-3 py-2 text-left transition-[border-color,box-shadow]",
                        active
                          ? "border-ink shadow-[0_0_0_1px_rgb(var(--ink))]"
                          : "border-border-strong hover:border-fg-subtle/70",
                      )}
                    >
                      <span className="flex items-center justify-between text-[13px] font-medium text-fg">
                        {d.label}
                        {active && <Check className="h-3.5 w-3.5" aria-hidden />}
                      </span>
                      <span className="block text-[11.5px] text-fg-muted">{DIVISION_HINT[d.value]}</span>
                    </button>
                  );
                })}
              </div>
            </Field>
          </Group>

          <Group icon={MapPin} title="Market" hint="Where the companies are. Region and city narrow the search.">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
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
                <Input id="region" value={values.region} onChange={set("region")} maxLength={100} placeholder="Any region" />
              </Field>
              <Field label="City" htmlFor="city" error={errors.city}>
                <Input id="city" value={values.city} onChange={set("city")} maxLength={100} placeholder="Any city" />
              </Field>
            </div>
          </Group>

          <Group icon={Building2} title="Companies" hint="Which companies qualify, and how many LeadFinder should aim for.">
            <Field label="Industry" htmlFor="industry" error={errors.industry}>
              {industryMode === "list" ? (
                <Select
                  id="industry"
                  className="sm:w-72"
                  value={values.industry}
                  onChange={(e) => {
                    if (e.target.value === CUSTOM) {
                      setIndustryMode("custom");
                      setValue("industry", "");
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
                <div className="flex gap-2 sm:w-96">
                  <Input id="industry" value={values.industry} onChange={set("industry")} maxLength={150} placeholder="Custom industry" autoFocus />
                  <Button variant="ghost" onClick={() => setIndustryMode("list")} aria-label="Back to industry list">
                    <X className="h-3.5 w-3.5" aria-hidden /> List
                  </Button>
                </div>
              )}
            </Field>
            <Field label="Company size" error={errors.company_size_min ?? errors.company_size_max}>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Company size">
                {CAMPAIGN_SIZE_RANGES.map((r) => (
                  <Chip key={r.label} active={values.size === sizeKey(r.min, r.max)} onClick={() => setValue("size", sizeKey(r.min, r.max))}>
                    {r.label.replace(" employees", "")}
                  </Chip>
                ))}
              </div>
            </Field>
            <Field label="Companies to find" htmlFor="count" required error={errors.target_company_count}>
              <div className="flex flex-wrap items-center gap-1.5">
                {TARGET_COUNTS.map((n) => (
                  <Chip key={n} active={values.target_company_count === String(n)} onClick={() => setValue("target_company_count", String(n))}>
                    {n}
                  </Chip>
                ))}
                <Input
                  id="count"
                  type="number"
                  min={1}
                  max={10000}
                  aria-label="Custom number of companies"
                  className="w-24"
                  value={values.target_company_count}
                  onChange={set("target_company_count")}
                  required
                />
              </div>
            </Field>
          </Group>

          <Group icon={Users} title="Decision-makers" hint="Job titles to reach at qualifying companies. Suggestions follow the division.">
            <Field label="Target roles" error={errors.target_roles}>
              <RolePicker
                division={values.tecomsa_division}
                selected={values.target_roles}
                onChange={(roles) => setValues((v) => ({ ...v, target_roles: roles }))}
              />
            </Field>
          </Group>

          <Group icon={Crosshair} title="Budget & notes" hint="Limits and anything the research team should know.">
            <Field
              label="Max. Lusha credit budget"
              htmlFor="budget"
              error={errors.max_lusha_credit_budget}
              hint="Stored for later phases. No credits are used now."
            >
              <Input id="budget" type="number" min={0} className="w-40" value={values.max_lusha_credit_budget} onChange={set("max_lusha_credit_budget")} placeholder="No limit" />
            </Field>
            <Field label="Additional instructions" htmlFor="instructions" error={errors.additional_instructions}>
              <Textarea
                id="instructions"
                value={values.additional_instructions}
                onChange={set("additional_instructions")}
                maxLength={5000}
                placeholder="e.g. Prefer family-owned groups with more than one branch."
              />
            </Field>
          </Group>
        </div>
      </div>

      <aside className="space-y-3 lg:sticky lg:top-8">
        <SearchBrief values={values} />
        <div className="flex gap-2">
          <Button variant="secondary" className="flex-1" onClick={() => router.back()}>
            Cancel
          </Button>
          <Button type="submit" className="flex-1" loading={saving}>
            {campaign ? "Save changes" : "Save as draft"}
          </Button>
        </div>
      </aside>
    </form>
  );
}
