"use client";

import { useCallback, useEffect, useState } from "react";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public fieldErrors: Record<string, string> = {},
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT";
  body?: unknown;
  /** Multipart upload; the browser sets the Content-Type boundary itself. */
  form?: FormData;
  query?: Query;
}

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  const qs = params.toString();
  return `/api${path}${qs ? `?${qs}` : ""}`;
}

interface ValidationIssue {
  loc?: (string | number)[];
  msg?: string;
}

function parseError(status: number, payload: unknown): ApiError {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (Array.isArray(detail)) {
    const fieldErrors: Record<string, string> = {};
    (detail as ValidationIssue[]).forEach((issue) => {
      const field = issue.loc?.filter((p) => p !== "body").join(".") || "form";
      fieldErrors[field] = (issue.msg ?? "Invalid value").replace(/^Value error, /, "");
    });
    return new ApiError(status, "Please correct the highlighted fields.", fieldErrors);
  }
  if (typeof detail === "string") return new ApiError(status, detail);
  if (status === 413) return new ApiError(status, "The file is too large to upload.");
  if (status === 403) return new ApiError(status, "You do not have permission to do this.");
  if (status === 404) return new ApiError(status, "This record no longer exists or you cannot access it.");
  if (status >= 500)
    return new ApiError(status, "The server hit an unexpected error. It has been logged; please try again.");
  return new ApiError(status, `The request failed (HTTP ${status}).`);
}

async function redirectToLogin() {
  // Clear any stale cookie, then send the user to the login page.
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
  const next = window.location.pathname + window.location.search;
  window.location.href = `/login?next=${encodeURIComponent(next)}`;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? (options.form ? "POST" : "GET"),
      headers: options.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: options.form ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "Cannot reach the LeadFinder server. Check your connection and try again.");
  }

  if (response.status === 401 && !path.startsWith("/auth/")) {
    await redirectToLogin();
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }
  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => null);
  if (!response.ok) throw parseError(response.status, payload);
  return payload as T;
}

/** Minimal data-fetching hook. Pass `null` as path to skip fetching. */
export function useApi<T>(path: string | null, query?: Query) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const queryKey = JSON.stringify(query ?? {});

  const load = useCallback(async () => {
    if (path === null) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api<T>(path, { query: JSON.parse(queryKey) as Query }));
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "Unexpected error while loading data."));
    } finally {
      setLoading(false);
    }
  }, [path, queryKey]);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, error, loading, reload: load };
}
