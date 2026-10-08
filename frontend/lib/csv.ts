/** Download rows as a UTF-8 CSV (with BOM so Excel reads Arabic/accents correctly). */
export function downloadCsv(filename: string, header: string[], rows: (string | number | null | undefined)[][]) {
  const escape = (v: string | number | null | undefined) => {
    const s = v == null ? "" : String(v);
    // A leading = + - @ tab or CR can run as a spreadsheet formula (HYPERLINK, DDE...). Only values that
    // are entirely a phone number ("+961 1 234 567") keep their first character.
    const phone = /^\+?[\d\s().\-/]+$/.test(s);
    const safe = /^[=+\-@\t\r]/.test(s) && !phone ? `'${s}` : s;
    return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
  };
  const text = [header, ...rows].map((r) => r.map(escape).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([String.fromCharCode(0xfeff) + text], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}
