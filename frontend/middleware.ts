import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "lf_session";
const backendUrl = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";

// The owner lock (backend app/core/owner_lock): any path but /health answers 503 while locked, so an unknown path
// tells locked (503) from open (404) without an endpoint that names the lock. Re-checked at most every 3 s.
const lock = { at: 0, locked: false };

async function isLocked(): Promise<boolean> {
  if (Date.now() - lock.at > 3000) {
    lock.locked = await fetch(`${backendUrl}/__status`, { cache: "no-store" })
      .then((r) => r.status === 503)
      .catch(() => false);
    lock.at = Date.now();
  }
  return lock.locked;
}

const UNAVAILABLE = `<!doctype html><html><head><meta charset="utf-8"><title>503 Service Unavailable</title></head>
<body style="font-family:sans-serif;margin:3rem"><h1>503 Service Unavailable</h1></body></html>`;

/**
 * Locked by the owner: every page (login included) is a bare error page, nothing of LeadFinder loads.
 * Otherwise, the first line of defence: unauthenticated visitors are redirected to /login. The backend still
 * validates the session on every API call - this check only avoids rendering protected pages for visitors with no
 * session cookie at all.
 */
export async function middleware(request: NextRequest) {
  if (await isLocked()) {
    return new NextResponse(UNAVAILABLE, {
      status: 503,
      headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
    });
  }
  const path = request.nextUrl.pathname;
  if (path.startsWith("/login") || path.startsWith("/api") || request.cookies.has(SESSION_COOKIE)) {
    return NextResponse.next();
  }
  const loginUrl = new URL("/login", request.url);
  const target = path + request.nextUrl.search;
  if (target !== "/") loginUrl.searchParams.set("next", target);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  // Everything except static build assets (the lock also covers the login page and the API proxy).
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
