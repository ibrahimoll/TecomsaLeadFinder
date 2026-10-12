// The browser only ever talks to this Next.js server. Requests to /api/* are
// proxied server-side to the FastAPI backend, so the session cookie stays
// same-origin and the backend URL is never exposed to the browser.
const backendUrl = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";
const production = process.env.NODE_ENV === "production";

// Content-Security-Policy. Next.js inlines its bootstrap scripts and styles, so 'unsafe-inline' is
// needed for script/style without a per-request nonce; everything else is locked to this origin plus
// the two external resources the UI uses (company logos, the OpenStreetMap embed and map tiles).
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${production ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://icons.duckduckgo.com https://tile.openstreetmap.org",
  "font-src 'self' data:",
  `connect-src 'self'${production ? "" : " ws: wss:"}`,
  "frame-src https://www.openstreetmap.org",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: { ignoreDuringBuilds: true },
  // The /api proxy defaults to a 30 s timeout; checking or importing a directory export of ~1,000 rows takes longer.
  // ponytail: raised timeout, not a fix for slow imports; move them to the worker queue if files grow.
  experimental: { proxyTimeout: 300_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Content-Security-Policy", value: csp },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          // HTTPS is terminated by the reverse proxy in production (see SECURITY.md).
          ...(production ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }] : []),
        ],
      },
    ];
  },
};

export default nextConfig;
