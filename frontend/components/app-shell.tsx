"use client";

import clsx from "clsx";
import { Activity, Building2, LayoutDashboard, LogOut, Megaphone, Shield } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { AuthContext } from "@/lib/auth";
import { ROLE_LABEL } from "@/lib/constants";
import type { User } from "@/types";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/campaigns", label: "Campaigns", icon: Megaphone },
  { href: "/companies", label: "Companies", icon: Building2 },
  { href: "/activity", label: "My Activity", icon: Activity },
];

function NavLink({ href, label, icon: Icon }: { href: string; label: string; icon: typeof Activity }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      className={clsx(
        "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm font-medium",
        active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
      )}
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      {label}
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    // api() redirects to /login on 401.
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => {
        window.location.href = "/login";
      });
  }, []);

  async function logout() {
    setSigningOut(true);
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    window.location.href = "/login";
  }

  if (!user) return <Loading label="Loading LeadFinder…" />;

  return (
    <AuthContext.Provider value={user}>
      <div className="flex min-h-screen">
        <aside className="fixed inset-y-0 left-0 hidden w-56 flex-col border-r border-slate-200 bg-white md:flex">
          <div className="border-b border-slate-200 px-4 py-3.5">
            <p className="text-xs font-semibold uppercase tracking-wider text-brand-700">TECOMSA</p>
            <p className="text-base font-semibold text-slate-900">LeadFinder AI</p>
          </div>
          <nav className="flex-1 space-y-0.5 p-2">
            {NAV.map((item) => (
              <NavLink key={item.href} {...item} />
            ))}
            {user.role === "ADMIN" && (
              <>
                <div className="my-2 border-t border-slate-200" />
                <NavLink href="/admin" label="Administration" icon={Shield} />
              </>
            )}
          </nav>
          <div className="border-t border-slate-200 p-3">
            <p className="truncate text-sm font-medium text-slate-900">{user.name}</p>
            <p className="truncate text-xs text-slate-500">{ROLE_LABEL[user.role]}</p>
            <button
              onClick={logout}
              disabled={signingOut}
              className="mt-2 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-slate-600 hover:bg-slate-100"
            >
              <LogOut className="h-4 w-4" aria-hidden /> {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </div>
        </aside>

        {/* Compact top bar for small screens */}
        <div className="fixed inset-x-0 top-0 z-10 flex items-center gap-1 overflow-x-auto border-b border-slate-200 bg-white px-2 py-2 md:hidden">
          {NAV.map((item) => (
            <NavLink key={item.href} {...item} />
          ))}
          {user.role === "ADMIN" && <NavLink href="/admin" label="Admin" icon={Shield} />}
          <button onClick={logout} className="ml-auto p-1.5 text-slate-600" aria-label="Sign out">
            <LogOut className="h-4 w-4" />
          </button>
        </div>

        <main className="flex-1 px-4 pb-10 pt-16 md:ml-56 md:px-8 md:pt-6">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>
    </AuthContext.Provider>
  );
}
