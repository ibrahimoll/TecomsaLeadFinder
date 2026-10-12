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

/** A Lebanese number written one way ("03/721121", "+96170074074" -> "+961 3 721 121", "+961 70 074 074"); a
 * foreign or unclear number is left as given. */
export function formatPhone(phone: string): string {
  const raw = phone.trim();
  const digits = raw.replace(/[^\d]/g, "");
  const lebanese = /^(00)?961/.test(digits) || raw.startsWith("0") || /^[1-9]\d{6,7}$/.test(digits);
  if (!lebanese || (raw.startsWith("+") && !raw.startsWith("+961"))) return raw;
  const n = digits.replace(/^(00)?961/, "").replace(/^0/, "");
  if (/^(7\d|81)\d{6}$/.test(n)) return `+961 ${n.slice(0, 2)} ${n.slice(2, 5)} ${n.slice(5)}`;
  if (/^[1-9]\d{6}$/.test(n)) return `+961 ${n[0]} ${n.slice(1, 4)} ${n.slice(4)}`;
  return raw;
}
