"use client";

import clsx from "clsx";
import { Building2, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Search, Settings, X, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { TecomsaLogo } from "@/components/brand";
import { Avatar, Toaster } from "@/components/ui";
import { api } from "@/lib/api";
import { AuthContext } from "@/lib/auth";
import { ROLE_LABEL } from "@/lib/constants";
import type { Me } from "@/types";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Other paths that belong to this item. */
  also?: string[];
}

const NAV: NavItem[] = [
  { href: "/find-leads", label: "Find Leads", icon: Search },
  { href: "/companies", label: "Companies", icon: Building2 },
  { href: "/settings", label: "Settings", icon: Settings, also: ["/admin"] },
];

function NavLink({ item, collapsed, onNavigate }: { item: NavItem; collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const active = [item.href, ...(item.also ?? [])].some((href) => pathname === href || pathname.startsWith(`${href}/`));
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      title={collapsed ? item.label : undefined}
      className={clsx(
        "group relative flex h-9 items-center gap-2.5 rounded-md text-[13.5px] transition-[background-color,color,box-shadow] duration-200",
        collapsed ? "justify-center px-0" : "px-2.5",
        active
          ? "bg-surface font-medium text-fg shadow-[0_0_0_1px_rgb(var(--border)),0_1px_2px_rgb(var(--fg)/0.06)] before:absolute before:-left-2 before:top-1/2 before:h-5 before:w-[3px] before:-translate-y-1/2 before:animate-pop-in before:rounded-r-full before:bg-accent"
          : "text-fg-muted hover:bg-fg/[0.05] hover:text-fg",
      )}
    >
      <Icon className={clsx("h-4 w-4 shrink-0 transition-colors duration-200", active ? "text-accent" : "text-fg-subtle group-hover:text-fg-muted")} strokeWidth={1.75} aria-hidden />
      {!collapsed && <span className="truncate">{item.label}</span>}
    </Link>
  );
}

function Sidebar({
  user,
  collapsed,
  onToggle,
  onNavigate,
  onLogout,
  signingOut,
}: {
  user: Me;
  collapsed: boolean;
  onToggle?: () => void;
  onNavigate?: () => void;
  onLogout: () => void;
  signingOut: boolean;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className={clsx("flex h-14 items-center", collapsed ? "justify-center px-2" : "gap-2.5 px-4")}>
        <Link href="/find-leads" className="flex items-center" aria-label="Tecomsa LeadFinder home">
          {collapsed ? <TecomsaLogo compact /> : <TecomsaLogo subtitle="LeadFinder" />}
        </Link>
        {onToggle && !collapsed && (
          <button
            type="button"
            onClick={onToggle}
            className="ml-auto rounded p-1 text-fg-subtle transition-colors hover:bg-fg/[0.06] hover:text-fg"
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
          >
            <PanelLeftClose className="h-4 w-4" strokeWidth={1.75} />
          </button>
        )}
      </div>

      <nav aria-label="Main" className={clsx("flex-1 overflow-y-auto py-2", collapsed ? "px-2" : "px-3")}>
        <div className="space-y-0.5">
          {NAV.map((item) => (
            <NavLink key={item.href} item={item} collapsed={collapsed} onNavigate={onNavigate} />
          ))}
        </div>
      </nav>

      {collapsed && onToggle && (
        <div className="flex justify-center pb-1">
          <button
            type="button"
            onClick={onToggle}
            className="rounded p-1.5 text-fg-subtle transition-colors hover:bg-fg/[0.06] hover:text-fg"
            aria-label="Expand sidebar"
            title="Expand sidebar"
          >
            <PanelLeftOpen className="h-4 w-4" strokeWidth={1.75} />
          </button>
        </div>
      )}

      <div className={collapsed ? "p-2" : "p-2.5"}>
        <div className={clsx("flex items-center gap-2.5 rounded-lg", collapsed ? "flex-col" : "border border-border bg-surface px-2 py-1.5 shadow-xs")}>
          <span title={collapsed ? `${user.name} · ${ROLE_LABEL[user.role]}` : undefined}>
            <Avatar name={user.name} size="sm" />
          </span>
          {!collapsed && (
            <div className="min-w-0 flex-1 leading-tight">
              <p className="truncate text-[13px] font-medium">{user.name}</p>
              <p className="truncate text-[11px] text-fg-subtle">{ROLE_LABEL[user.role]}</p>
            </div>
          )}
          <button
            type="button"
            onClick={onLogout}
            disabled={signingOut}
            className="rounded p-1.5 text-fg-subtle transition-colors hover:bg-fg/[0.06] hover:text-fg"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="h-4 w-4" strokeWidth={1.75} />
          </button>
        </div>
      </div>
    </div>
  );
}

const COLLAPSE_KEY = "lf.sidebar.collapsed";

const ME_KEY = "lf.me";

export function AppShell({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [slow, setSlow] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    // The tab's last answer to "who is signed in" opens the page at once (UI only: the backend checks every
    // request); the real answer replaces it, and api() redirects to /login on 401.
    try {
      const cached = sessionStorage.getItem(ME_KEY);
      if (cached) setUser(JSON.parse(cached) as Me);
    } catch {
      /* storage unavailable: wait for the server */
    }
    const timer = setTimeout(() => setSlow(true), 400); // no splash flash on a fast answer
    api<Me>("/auth/me")
      .then((me) => {
        setUser(me);
        try {
          sessionStorage.setItem(ME_KEY, JSON.stringify(me));
        } catch {
          /* ignore */
        }
      })
      .catch(() => {
        window.location.href = "/login";
      })
      .finally(() => clearTimeout(timer));
    try {
      setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* storage unavailable: keep expanded */
    }
  }, []);

  useEffect(() => setMobileOpen(false), [pathname]);

  function toggleCollapsed() {
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !c;
    });
  }

  async function logout() {
    setSigningOut(true);
    try {
      sessionStorage.removeItem(ME_KEY);
    } catch {
      /* ignore */
    }
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    window.location.href = "/login";
  }

  if (!user) {
    if (!slow) return <div className="min-h-screen bg-bg" aria-busy="true" />;
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-bg" aria-busy="true" aria-label="Loading LeadFinder">
        <TecomsaLogo subtitle="LeadFinder" size="lg" className="animate-page-in" />
        <span className="relative h-1 w-40 overflow-hidden rounded-full bg-border" aria-hidden>
          <span className="absolute inset-y-0 left-0 w-1/3 animate-[loading-bar_1.1s_ease-in-out_infinite] rounded-full bg-accent" />
        </span>
      </div>
    );
  }

  return (
    <AuthContext.Provider value={user}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <div className="flex min-h-screen">
        <aside
          className={clsx(
            "fixed inset-y-0 left-0 z-20 hidden bg-sidebar transition-[width] duration-200 ease-out md:block",
            collapsed ? "w-14" : "w-[232px]",
          )}
        >
          <Sidebar
            user={user}
            collapsed={collapsed}
            onToggle={toggleCollapsed}
            onLogout={logout}
            signingOut={signingOut}
          />
        </aside>

        {/* Small screens: top bar + slide-over navigation */}
        <div className="fixed inset-x-0 top-0 z-20 flex h-12 items-center gap-2 border-b border-border bg-surface/95 px-3 backdrop-blur md:hidden">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="rounded p-1.5 text-fg-muted hover:bg-surface-hover"
            aria-label="Open navigation"
            aria-expanded={mobileOpen}
          >
            <Menu className="h-5 w-5" />
          </button>
          <TecomsaLogo subtitle="LeadFinder" />
        </div>
        {mobileOpen && (
          <div className="fixed inset-0 z-30 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
            <button className="absolute inset-0 bg-ink/30" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />
            <div className="absolute inset-y-0 left-0 w-64 animate-[fade-in_150ms_ease-out] border-r border-border bg-sidebar">
              <button
                type="button"
                onClick={() => setMobileOpen(false)}
                className="absolute right-2 top-2.5 z-10 rounded p-1.5 text-fg-muted hover:bg-surface-hover"
                aria-label="Close navigation"
              >
                <X className="h-4 w-4" />
              </button>
              <Sidebar
                user={user}
                collapsed={false}
                onLogout={logout}
                signingOut={signingOut}
                onNavigate={() => setMobileOpen(false)}
              />
            </div>
          </div>
        )}

        <main
          id="main"
          className={clsx(
            "min-w-0 flex-1 pt-12 transition-[margin] duration-200 ease-out md:py-2 md:pr-2",
            collapsed ? "md:ml-14" : "md:ml-[232px]",
          )}
        >
          {/* The inset page panel: one raised white surface per page, the canvas stays navigation. */}
          <div className="min-h-[calc(100vh-3rem)] bg-surface px-4 pb-16 pt-5 md:min-h-[calc(100vh-1rem)] md:rounded-xl md:border md:border-border md:px-8 md:pt-8 md:shadow-panel">
            <div key={pathname} className="mx-auto max-w-[1320px] animate-page-in">
              {children}
            </div>
          </div>
        </main>
      </div>
      <Toaster />
    </AuthContext.Provider>
  );
}
