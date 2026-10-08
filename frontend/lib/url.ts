/**
 * Links built from untrusted data (company websites from OSM / Overture / Odoo imports, provider
 * profile URLs, crawled source pages) must never become `javascript:` / `data:` links: only absolute
 * http(s) URLs are rendered as links.
 */
export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}

/** An in-app path to return to after login; anything else (other sites, `//x`, `/\x`) goes to Find Leads. */
export function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || /[\\\u0000-\u001f]/.test(value)) return "/find-leads";
  try {
    const resolved = new URL(value, window.location.origin);
    return resolved.origin === window.location.origin ? resolved.pathname + resolved.search + resolved.hash : "/find-leads";
  } catch {
    return "/find-leads";
  }
}
