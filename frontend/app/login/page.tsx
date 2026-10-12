"use client";

import { ArrowRight } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { TecomsaLogo } from "@/components/brand";
import { Alert, Button, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { safeNext } from "@/lib/url";

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
      <Button type="submit" className="group h-10 w-full" loading={submitting}>
        Continue <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </Button>
    </form>
  );
}

const POINTS = [
  "Lebanese companies found by industry and area, the best fit for Odoo, Frinzo and IT first",
  "Decision-makers and their mobiles from directories, the web and your team's calls",
  "Every number labelled with where it came from, and confirmed by the people who call it",
];

export default function LoginPage() {
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      {/* Brand cover, after the TECOMSA company profile: deep red field with a lighter sweep. */}
      <aside
        className="relative hidden overflow-hidden text-white lg:flex lg:flex-col lg:justify-between lg:p-12"
        style={{
          background:
            "radial-gradient(120% 90% at 85% 15%, rgb(214 28 36) 0%, transparent 60%), linear-gradient(150deg, rgb(150 6 12) 0%, rgb(196 18 26) 50%, rgb(110 4 8) 100%)",
        }}
      >
        <TecomsaLogo inverted size="lg" subtitle="Technology of Tomorrow" className="relative animate-page-in" />
        <div className="stagger relative max-w-md">
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-white/70">LeadFinder</p>
          <p className="mt-3 font-display text-[30px] font-semibold leading-[38px] tracking-[-0.02em]">
            Find the right companies, and the right person to call.
          </p>
          <ul className="mt-8 space-y-3">
            {POINTS.map((p) => (
              <li key={p} className="flex gap-3 text-[14px] leading-5 text-white/85">
                <span className="mt-[6px] h-2 w-2 shrink-0 bg-white" aria-hidden />
                {p}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-white/60">Smarter Tech · Stronger Business · Internal system</p>
      </aside>

      <main className="flex items-center justify-center bg-surface px-4 py-12">
        <div className="w-full max-w-[340px] animate-page-in">
          <TecomsaLogo subtitle="LeadFinder" className="mb-10 lg:hidden" />
          <h1 className="text-[24px] font-semibold tracking-[-0.02em]">Sign in</h1>
          <p className="mb-6 mt-1 text-[14px] text-fg-muted">Use your TECOMSA work account.</p>
          <Suspense>
            <LoginForm />
          </Suspense>
          <p className="mt-6 text-xs text-fg-subtle">Accounts are created by a LeadFinder administrator.</p>
        </div>
      </main>
    </div>
  );
}
