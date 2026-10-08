/** Host of a website URL for display ("https://www.abc.com/about" -> "abc.com"), or null if unparsable. */
export function displayDomain(url: string): string | null {
  try {
    const host = new URL(url.includes("://") ? url : `https://${url}`).hostname;
    return host.replace(/^www\./, "") || null;
  } catch {
    return null;
  }
}
