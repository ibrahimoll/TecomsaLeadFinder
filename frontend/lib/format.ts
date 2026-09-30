const dateFormat = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" });
const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const money = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function formatDate(value: string | null | undefined): string {
  return value ? dateFormat.format(new Date(value)) : "—";
}

export function formatDateTime(value: string | null | undefined): string {
  return value ? dateTimeFormat.format(new Date(value)) : "—";
}

export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return money.format(Number(value));
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function dash(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

export function location(city: string | null | undefined, country: string | null | undefined): string {
  return [city, country].filter(Boolean).join(", ") || "—";
}

export function sizeRange(min: number | null, max: number | null): string {
  if (min === null && max === null) return "Any size";
  if (max === null) return `${min}+ employees`;
  if (min === null) return `Up to ${max} employees`;
  return `${min}–${max} employees`;
}
