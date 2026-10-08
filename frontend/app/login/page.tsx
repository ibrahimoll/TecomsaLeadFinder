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
      <Button type="submit" className="h-9 w-full" loading={submitting}>
        Continue
      </Button>
    </form>
  );
}

const POINTS = [
  "Every company checked against TECOMSA's Odoo before anyone reaches out",
  "Campaigns that define the market, industry and decision-makers to find",
  "One shared record per company: contacts, relationship and activity",
];

export default function LoginPage() {
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <aside className="relative hidden overflow-hidden bg-ink text-white lg:flex lg:flex-col lg:justify-between lg:p-10">
        {/* Fine dot grid: texture, not decoration. */}
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{ backgroundImage: "radial-gradient(rgb(255 255 255) 1px, transparent 1px)", backgroundSize: "18px 18px" }}
          aria-hidden
        />
        <div className="relative flex items-center gap-2.5">
          <span className="relative flex h-7 w-7 items-center justify-center rounded-md bg-white" aria-hidden>
            <svg viewBox="0 0 16 16" className="h-4 w-4 text-ink" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <path d="M4 3.5v9h7" />
            </svg>
            <span className="absolute right-[3px] top-[3px] h-1.5 w-1.5 rounded-full bg-[rgb(var(--accent))]" />
          </span>
          <span className="text-[14px] font-semibold tracking-[-0.01em]">
            LeadFinder <span className="font-normal text-white/50">TECOMSA</span>
          </span>
        </div>
        <div className="relative max-w-md">
          <p className="text-[26px] font-semibold leading-[34px] tracking-[-0.02em]">Find the right companies. Never chase the ones you already know.</p>
          <ul className="mt-8 space-y-3">
            {POINTS.map((p) => (
              <li key={p} className="flex gap-3 text-[13.5px] leading-5 text-white/70">
                <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-[rgb(var(--accent))]" aria-hidden />
                {p}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-white/40">Internal system · TECOMSA</p>
      </aside>

      <main className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-[340px]">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="relative flex h-7 w-7 items-center justify-center rounded-md bg-ink" aria-hidden>
              <svg viewBox="0 0 16 16" className="h-4 w-4 text-white" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <path d="M4 3.5v9h7" />
              </svg>
            </span>
            <span className="text-[14px] font-semibold">LeadFinder</span>
          </div>
          <h1 className="text-[20px] font-semibold tracking-[-0.018em]">Sign in</h1>
          <p className="mb-6 mt-1 text-[13px] text-fg-muted">Use your TECOMSA work account.</p>
          <Suspense>
            <LoginForm />
          </Suspense>
          <p className="mt-6 text-xs text-fg-subtle">Accounts are created by a LeadFinder administrator.</p>
        </div>
      </main>
    </div>
  );
}
