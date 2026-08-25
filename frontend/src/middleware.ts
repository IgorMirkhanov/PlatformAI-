import { NextResponse, type NextRequest } from "next/server";

/** Keep in sync with `lib/auth/tokens.ts` cookie names. */
const ACCESS_TOKEN_COOKIE = "mpai_access_token";
const PLATFORM_ROLE_COOKIE = "mpai_platform_role";

const PUBLIC_ROUTES = [
  "/",
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password",
  "/accept-invite",
  "/integrations/hub/oauth-result",
] as const;

function isPublicPath(pathname: string): boolean {
  return PUBLIC_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );
}

function isAdminPath(pathname: string): boolean {
  return pathname === "/admin" || pathname.startsWith("/admin/");
}

/** Login / 403 pages must stay reachable without platform-staff JWT claims. */
function isAdminGateExemptPath(pathname: string): boolean {
  return pathname === "/admin/login" || pathname === "/admin/forbidden";
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    let b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const pad = (4 - (b64.length % 4)) % 4;
    b64 += "=".repeat(pad);
    const json = atob(b64);
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function hasValidAccessToken(request: NextRequest): boolean {
  const raw = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
  if (!raw) return false;
  const token = decodeURIComponent(raw);

  // Legacy HMAC impersonation tokens — backend validates signature/expiry.
  if (token.startsWith("imp_")) return true;

  const payload = decodeJwtPayload(token);
  if (!payload) return false;

  const exp = payload.exp;
  if (typeof exp !== "number") {
    // Reject unsigned/opaque non-imp tokens without exp.
    return false;
  }
  return exp * 1000 > Date.now();
}

function getPlatformRole(request: NextRequest): string {
  const raw = request.cookies.get(PLATFORM_ROLE_COOKIE)?.value || "USER";
  return decodeURIComponent(raw).toUpperCase();
}

/**
 * Admin Panel is superadmin-only. Prefer JWT claims; fall back to the
 * platform-role cookie (UX hint). Cookie alone is not security — every
 * /api/v1/admin/* route re-checks is_superadmin server-side.
 */
function isPlatformSuperadmin(request: NextRequest): boolean {
  const raw = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
  if (raw) {
    const token = decodeURIComponent(raw);
    // Impersonation tokens must never reach /admin.
    if (token.startsWith("imp_")) return false;
    const payload = decodeJwtPayload(token);
    if (payload?.typ === "impersonation") return false;
    if (payload?.is_superuser === true || payload?.is_superadmin === true) {
      return true;
    }
    const claimRole = String(payload?.role ?? "").toUpperCase();
    if (claimRole === "SUPERADMIN" || claimRole === "SUPER_ADMIN") return true;
    if (payload) return false;
  }
  return getPlatformRole(request) === "SUPERADMIN";
}

function loginRedirect(request: NextRequest, extra?: Record<string, string>): NextResponse {
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.search = "";
  const from = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  if (from && from !== "/login") {
    loginUrl.searchParams.set("from", from);
  }
  if (extra) {
    Object.entries(extra).forEach(([key, value]) => {
      loginUrl.searchParams.set(key, value);
    });
  }
  return NextResponse.redirect(loginUrl);
}

function redirectAuthenticatedAwayFromAuthPages(request: NextRequest): NextResponse | null {
  const { pathname } = request.nextUrl;
  if (!isPublicPath(pathname)) return null;
  if (!hasValidAccessToken(request)) return null;
  if (request.nextUrl.searchParams.get("expired")) return null;

  // Allow reset-password even when a stale cookie exists (token in query is source of truth).
  if (pathname === "/reset-password" || pathname.startsWith("/reset-password/")) {
    return null;
  }

  if (pathname === "/login" || pathname === "/register" || pathname.startsWith("/forgot-password")) {
    const from = request.nextUrl.searchParams.get("from");
    if (from && from.startsWith("/") && !from.startsWith("//")) {
      return NextResponse.redirect(new URL(from, request.url));
    }
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return null;
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/uploads") ||
    pathname.startsWith("/ws") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  const authPageRedirect = redirectAuthenticatedAwayFromAuthPages(request);
  if (authPageRedirect) return authPageRedirect;

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  if (isAdminPath(pathname)) {
    if (isAdminGateExemptPath(pathname)) {
      return NextResponse.next();
    }
    if (!hasValidAccessToken(request)) {
      const loginUrl = request.nextUrl.clone();
      loginUrl.pathname = "/admin/login";
      loginUrl.search = "";
      const from = `${request.nextUrl.pathname}${request.nextUrl.search}`;
      if (from && from !== "/admin/login") {
        loginUrl.searchParams.set("from", from);
      }
      return NextResponse.redirect(loginUrl);
    }
    if (!isPlatformSuperadmin(request)) {
      return NextResponse.redirect(new URL("/admin/forbidden", request.url));
    }
    return NextResponse.next();
  }

  // All remaining app routes require a valid access cookie.
  if (!hasValidAccessToken(request)) {
    return loginRedirect(request);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
