// The browser only ever talks to this Next.js server. Requests to /api/* are
// proxied server-side to the FastAPI backend, so the session cookie stays
// same-origin and the backend URL is never exposed to the browser.
const backendUrl = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: { ignoreDuringBuilds: true },
  experimental: {
    // Proxied request bodies are cut at 10 MB by default; Odoo exports may be up to
    // 20 MB (the backend enforces IMPORT_MAX_BYTES), so allow a little headroom.
    middlewareClientMaxBodySize: "25mb",
  },
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
        ],
      },
    ];
  },
};

export default nextConfig;
