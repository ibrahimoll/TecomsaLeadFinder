const dateFormat = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" });
const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDate(value: string | null | undefined): string {
  return value ? dateFormat.format(new Date(value)) : "—";
}

export function formatDateTime(value: string | null | undefined): string {
  return value ? dateTimeFormat.format(new Date(value)) : "—";
}

/** A Lebanese mobile (03 / 70-79 / 81), as the backend's contact_intelligence.LEBANON_MOBILE: often reaches the owner
 * or a manager of a small company directly. */
export function isLebaneseMobile(phone: string): boolean {
  const national = phone.replace(/[^\d]/g, "").replace(/^(00)?961/, "").replace(/^0/, "");
  return /^(3\d{6}|7\d{7}|81\d{6})$/.test(national);
}
