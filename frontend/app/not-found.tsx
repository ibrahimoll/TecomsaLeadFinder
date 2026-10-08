import Link from "next/link";

import { TecomsaLogo } from "@/components/brand";

export default function NotFound() {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-bg px-4 text-center">
      <TecomsaLogo subtitle="LeadFinder" className="mb-10 animate-page-in" />
      <p className="animate-page-in font-display text-[88px] font-semibold leading-none tracking-[-0.04em] text-accent">404</p>
      <h1 className="mt-3 text-[22px] font-semibold tracking-[-0.02em]">Page not found</h1>
      <p className="mt-1 max-w-sm text-[14px] text-fg-muted">The page you are looking for does not exist or has moved.</p>
      <Link
        href="/find-leads"
        className="mt-6 inline-flex h-9 items-center rounded bg-accent px-4 text-[13.5px] font-medium text-white shadow-[0_1px_2px_rgb(var(--accent)/0.3)] transition-[transform,background-color] hover:-translate-y-px hover:bg-accent-hover"
      >
        Back to Find Leads
      </Link>
    </div>
  );
}
