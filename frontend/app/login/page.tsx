"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { Alert, Button, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

function safeNext(value: string | null): string {
  // Only allow internal paths to avoid open redirects.
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/dashboard";
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api("/auth/login", { method: "POST", body: { email, password } });
      router.replace(safeNext(params.get("next")));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to sign in. Please try again.");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {error && <Alert>{error}</Alert>}
      <Field label="Work email" htmlFor="email">
        <Input
          id="email"
          type="email"
          autoComplete="username"
          required
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </Field>
      <Field label="Password" htmlFor="password">
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
      <Button type="submit" className="w-full" disabled={submitting}>
        {submitting ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4">
      <div className="w-full max-w-[360px]">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded bg-fg text-xs font-bold text-white" aria-hidden>
            LF
          </span>
          <div className="leading-tight">
            <h1 className="text-[15px] font-semibold">LeadFinder</h1>
            <p className="text-xs text-fg-muted">TECOMSA sales intelligence</p>
          </div>
        </div>
        <div className="rounded-lg border border-border bg-surface p-6">
          <h2 className="mb-4 text-[15px] font-semibold">Sign in</h2>
          <Suspense>
            <LoginForm />
          </Suspense>
        </div>
        <p className="mt-4 text-xs text-fg-muted">
          Internal system. Accounts are created by a LeadFinder administrator.
        </p>
      </div>
    </div>
  );
}
