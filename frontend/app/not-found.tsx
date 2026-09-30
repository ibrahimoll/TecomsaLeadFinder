import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 text-center">
      <p className="text-xs font-medium text-fg-muted">404</p>
      <h1 className="mt-1 text-lg font-semibold">Page not found</h1>
      <p className="mt-1 text-[13px] text-fg-muted">The page you are looking for does not exist.</p>
      <Link href="/dashboard" className="mt-4 text-[13px] font-medium text-accent hover:underline">
        Go to dashboard
      </Link>
    </div>
  );
}
