"use client";

import clsx from "clsx";
import {
  Activity,
  Building2,
  ClipboardList,
  Database,
  History,
  LayoutDashboard,
  LogOut,
  Megaphone,
  Menu,
  Settings,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Avatar, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { AuthContext } from "@/lib/auth";
import { ROLE_LABEL } from "@/lib/constants";
import type { Me } from "@/types";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

function navGroups(user: Me): { label?: string; items: NavItem[] }[] {
  const groups: { label?: string; items: NavItem[] }[] = [
    {
      items: [
        { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
        { href: "/companies", label: "Companies", icon: Building2 },
        { href: "/campaigns", label: "Campaigns", icon: Megaphone },
        { href: "/activity", label: "My activity", icon: Activity },
      ],
    },
  ];
  if (user.capabilities.view_crm) {
    groups.push({
      label: "CRM",
      items: [
        { href: "/crm", label: "CRM records", icon: ClipboardList },
        { href: "/sales-team", label: "Sales team", icon: Users },
      ],
    });
  }
  if (user.capabilities.run_imports) {
    groups.push({
      label: "Data sources",
      items: [
        { href: "/data-sources/odoo", label: "Odoo imports", icon: Database },
        { href: "/imports", label: "Import history", icon: History },
      ],
    });
  }
  if (user.capabilities.manage_users) {
    groups.push({ label: "Admin", items: [{ href: "/admin", label: "Administration", icon: Settings }] });
  }
  return groups;
}

function NavLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const pathname = usePathname();
  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={clsx(
        "flex h-8 items-center gap-2.5 rounded px-2 text-[13px] transition-colors",
        active ? "bg-surface-hover font-medium text-fg" : "text-fg-muted hover:bg-surface-hover hover:text-fg",
      )}
    >
      <Icon className={clsx("h-4 w-4 shrink-0", active ? "text-fg" : "text-fg-subtle")} aria-hidden />
      {item.label}
    </Link>
  );
}

function Sidebar({ user, onNavigate, onLogout, signingOut }: {
  user: Me;
  onNavigate?: () => void;
  onLogout: () => void;
  signingOut: boolean;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 items-center gap-2 px-4">
        <span className="flex h-6 w-6 items-center justify-center rounded bg-fg text-2xs font-bold text-white" aria-hidden>
          LF
        </span>
        <div className="leading-tight">
          <p className="text-[13px] font-semibold">LeadFinder</p>
          <p className="text-2xs text-fg-subtle">TECOMSA</p>
        </div>
      </div>
      <nav aria-label="Main" className="flex-1 space-y-4 overflow-y-auto px-2 py-2">
        {navGroups(user).map((group, i) => (
          <div key={group.label ?? i}>
            {group.label && (
              <p className="mb-1 px-2 text-2xs font-medium uppercase tracking-wider text-fg-subtle">{group.label}</p>
            )}
            <div className="space-y-px">
              {group.items.map((item) => (
                <NavLink key={item.href} item={item} onNavigate={onNavigate} />
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="border-t border-border p-2">
        <div className="flex items-center gap-2 rounded px-2 py-1.5">
          <Avatar name={user.name} size="sm" />
          <div className="min-w-0 flex-1 leading-tight">
            <p className="truncate text-[13px] font-medium">{user.name}</p>
            <p className="truncate text-2xs text-fg-muted">{ROLE_LABEL[user.role]}</p>
          </div>
          <button
            type="button"
            onClick={onLogout}
            disabled={signingOut}
            className="rounded p-1.5 text-fg-subtle hover:bg-surface-hover hover:text-fg"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    // api() redirects to /login on 401.
    api<Me>("/auth/me")
      .then(setUser)
      .catch(() => {
        window.location.href = "/login";
      });
  }, []);

  useEffect(() => setMobileOpen(false), [pathname]);

  async function logout() {
    setSigningOut(true);
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    window.location.href = "/login";
  }

  if (!user) {
    return (
      <div className="flex min-h-screen" aria-busy="true" aria-label="Loading LeadFinder">
        <div className="hidden w-56 border-r border-border bg-surface md:block" />
        <div className="flex-1 space-y-3 p-8">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  return (
    <AuthContext.Provider value={user}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <div className="flex min-h-screen">
        <aside className="fixed inset-y-0 left-0 z-20 hidden w-56 border-r border-border bg-surface md:block">
          <Sidebar user={user} onLogout={logout} signingOut={signingOut} />
        </aside>

        {/* Small screens: top bar + slide-over navigation */}
        <div className="fixed inset-x-0 top-0 z-20 flex h-12 items-center gap-2 border-b border-border bg-surface px-3 md:hidden">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="rounded p-1.5 text-fg-muted hover:bg-surface-hover"
            aria-label="Open navigation"
            aria-expanded={mobileOpen}
          >
            <Menu className="h-5 w-5" />
          </button>
          <p className="text-[13px] font-semibold">LeadFinder</p>
        </div>
        {mobileOpen && (
          <div className="fixed inset-0 z-30 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
            <button className="absolute inset-0 bg-fg/30" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />
            <div className="absolute inset-y-0 left-0 w-64 border-r border-border bg-surface">
              <button
                type="button"
                onClick={() => setMobileOpen(false)}
                className="absolute right-2 top-2.5 rounded p-1.5 text-fg-muted hover:bg-surface-hover"
                aria-label="Close navigation"
              >
                <X className="h-4 w-4" />
              </button>
              <Sidebar user={user} onLogout={logout} signingOut={signingOut} onNavigate={() => setMobileOpen(false)} />
            </div>
          </div>
        )}

        <main id="main" className="min-w-0 flex-1 px-4 pb-12 pt-16 md:ml-56 md:px-8 md:pt-7">
          <div className="mx-auto max-w-[1280px]">{children}</div>
        </main>
      </div>
    </AuthContext.Provider>
  );
}
