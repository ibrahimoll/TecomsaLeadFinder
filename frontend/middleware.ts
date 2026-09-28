import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "lf_session";

/**
 * First line of defence: unauthenticated visitors are redirected to /login.
 * The backend still validates the session on every API call - this check only
 * avoids rendering protected pages for visitors with no session cookie at all.
 */
export function middleware(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) {
    return NextResponse.next();
  }
  const loginUrl = new URL("/login", request.url);
  const target = request.nextUrl.pathname + request.nextUrl.search;
  if (target !== "/") loginUrl.searchParams.set("next", target);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  // Everything except the login page, the API proxy and static assets.
  matcher: ["/((?!login|api|_next/static|_next/image|favicon.ico).*)"],
};
