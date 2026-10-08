"use client";

import clsx from "clsx";
import {
  Activity,
  Building2,
  ClipboardList,
  DatabaseZap,
  LayoutDashboard,
  LogOut,
  Megaphone,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Radar,
  Search,
  Settings,
  Upload,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { CommandPalette, type PaletteCommand } from "@/components/command-palette";
import { Avatar, Kbd, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { AuthContext } from "@/lib/auth";
import { ROLE_LABEL } from "@/lib/constants";
import type { Me } from "@/types";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Other paths that belong to this item (e.g. import detail pages). */
  also?: string[];
}

function navGroups(user: Me): { label?: string; items: NavItem[] }[] {
  const groups: { label?: string; items: NavItem[] }[] = [
    {
      items: [
        { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
        { href: "/discovery", label: "Find companies", icon: Radar },
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
      label: "Data",
      items: [{ href: "/data-sources/odoo", label: "Odoo imports", icon: DatabaseZap, also: ["/imports"] }],
    });
  }
  if (user.capabilities.manage_users) {
    groups.push({ label: "Admin", items: [{ href: "/admin", label: "Administration", icon: Settings }] });
  }
  return groups;
}

function paletteCommands(user: Me): PaletteCommand[] {
  const pages = navGroups(user).flatMap((g) => g.items);
  const commands: PaletteCommand[] = pages.map((p) => ({ id: p.href, label: p.label, group: "Go to", href: p.href, icon: p.icon }));
  commands.push(
    { id: "find", label: "Find companies", group: "Actions", href: "/discovery", icon: Radar, keywords: "discover search new prospects overture" },
    { id: "new-company", label: "Add company", group: "Actions", href: "/companies/new", icon: Plus, keywords: "create new company" },
    { id: "new-campaign", label: "New campaign", group: "Actions", href: "/campaigns/new", icon: Plus, keywords: "create lead search" },
    { id: "protected", label: "Show protected companies", group: "Actions", href: "/companies?protected=true", icon: Building2, keywords: "odoo existing" },
    { id: "available", label: "Show available companies", group: "Actions", href: "/companies?protected=false", icon: Building2, keywords: "prospects new" },
  );
  if (user.capabilities.run_imports) {
    commands.push({ id: "import", label: "Import Odoo file", group: "Actions", href: "/data-sources/odoo", icon: Upload, keywords: "upload contacts crm excel xlsx csv" });
  }
  return commands;
}

/** Brand mark: an ink tile with a signal dot, the one place the accent appears in the chrome. */
function LogoMark() {
  return (
    <span className="relative flex h-6 w-6 shrink-0 items-center justify-center rounded-[5px] bg-ink" aria-hidden>
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-white" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <path d="M4 3.5v9h7" />
      </svg>
      <span className="absolute right-[3px] top-[3px] h-1.5 w-1.5 rounded-full bg-[rgb(var(--accent))] ring-2 ring-ink" />
    </span>
  );
}

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
        "group relative flex h-8 items-center gap-2.5 rounded-md text-[13px] transition-colors",
        collapsed ? "justify-center px-0" : "px-2.5",
        active
          ? "bg-surface font-medium text-fg shadow-[0_0_0_1px_rgb(var(--border)),0_1px_2px_rgb(17_17_20/0.05)]"
          : "text-fg-muted hover:bg-black/[0.04] hover:text-fg",
      )}
    >
      <Icon className={clsx("h-4 w-4 shrink-0", active ? "text-fg" : "text-fg-subtle group-hover:text-fg-muted")} strokeWidth={1.75} aria-hidden />
      {!collapsed && <span className="truncate">{item.label}</span>}
    </Link>
  );
}

function Sidebar({
  user,
  collapsed,
  onToggle,
  onSearch,
  onNavigate,
  onLogout,
  signingOut,
}: {
  user: Me;
  collapsed: boolean;
  onToggle?: () => void;
  onSearch: () => void;
  onNavigate?: () => void;
  onLogout: () => void;
  signingOut: boolean;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className={clsx("flex h-12 items-center", collapsed ? "justify-center px-2" : "gap-2.5 px-4")}>
        <Link href="/dashboard" className="flex items-center gap-2.5" aria-label="LeadFinder home">
          <LogoMark />
          {!collapsed && (
            <span className="text-[13.5px] font-semibold tracking-[-0.01em]">
              LeadFinder<span className="ml-1.5 font-normal text-fg-subtle">TECOMSA</span>
            </span>
          )}
        </Link>
        {onToggle && !collapsed && (
          <button
            type="button"
            onClick={onToggle}
            className="ml-auto rounded p-1 text-fg-subtle transition-colors hover:bg-black/[0.05] hover:text-fg"
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
          >
            <PanelLeftClose className="h-4 w-4" strokeWidth={1.75} />
          </button>
        )}
      </div>

      <div className={clsx("pb-2 pt-1", collapsed ? "px-2" : "px-3")}>
        <button
          type="button"
          onClick={onSearch}
          title={collapsed ? "Search (Ctrl K)" : undefined}
          className={clsx(
            "flex h-8 w-full items-center gap-2 rounded-md border border-border bg-surface text-[13px] text-fg-subtle shadow-[0_1px_0_rgb(17_17_20/0.03)] transition-colors hover:border-border-strong hover:text-fg-muted",
            collapsed ? "justify-center" : "px-2.5",
          )}
        >
          <Search className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} aria-hidden />
          {!collapsed && (
            <>
              <span className="flex-1 text-left">Search…</span>
              <Kbd>Ctrl K</Kbd>
            </>
          )}
          {collapsed && <span className="sr-only">Search</span>}
        </button>
      </div>

      <nav aria-label="Main" className={clsx("flex-1 space-y-5 overflow-y-auto py-2", collapsed ? "px-2" : "px-3")}>
        {navGroups(user).map((group, i) => (
          <div key={group.label ?? i}>
            {group.label &&
              (collapsed ? (
                <div className="mx-2 mb-2 h-px bg-border" aria-hidden />
              ) : (
                <p className="mb-1 px-2.5 text-[11px] font-medium text-fg-subtle">{group.label}</p>
              ))}
            <div className="space-y-0.5">
              {group.items.map((item) => (
                <NavLink key={item.href} item={item} collapsed={collapsed} onNavigate={onNavigate} />
              ))}
            </div>
          </div>
        ))}
      </nav>

      {collapsed && onToggle && (
        <div className="flex justify-center pb-1">
          <button
            type="button"
            onClick={onToggle}
            className="rounded p-1.5 text-fg-subtle transition-colors hover:bg-black/[0.05] hover:text-fg"
            aria-label="Expand sidebar"
            title="Expand sidebar"
          >
            <PanelLeftOpen className="h-4 w-4" strokeWidth={1.75} />
          </button>
        </div>
      )}

      <div className={clsx("border-t border-border", collapsed ? "p-2" : "p-2.5")}>
        <div className={clsx("flex items-center gap-2.5 rounded-md", collapsed ? "flex-col" : "px-1.5 py-1")}>
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
            className="rounded p-1.5 text-fg-subtle transition-colors hover:bg-black/[0.05] hover:text-fg"
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

export function AppShell({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    // api() redirects to /login on 401.
    api<Me>("/auth/me")
      .then(setUser)
      .catch(() => {
        window.location.href = "/login";
      });
    try {
      setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* storage unavailable: keep expanded */
    }
  }, []);

  useEffect(() => setMobileOpen(false), [pathname]);

  // Ctrl/⌘ K opens the command palette anywhere in the app.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const commands = useMemo(() => (user ? paletteCommands(user) : []), [user]);

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
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    window.location.href = "/login";
  }

  if (!user) {
    return (
      <div className="flex min-h-screen" aria-busy="true" aria-label="Loading LeadFinder">
        <div className="hidden w-[232px] border-r border-border bg-sidebar md:block" />
        <div className="flex-1 space-y-4 p-8">
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
        <aside
          className={clsx(
            "fixed inset-y-0 left-0 z-20 hidden border-r border-border bg-sidebar transition-[width] duration-200 ease-out md:block",
            collapsed ? "w-14" : "w-[232px]",
          )}
        >
          <Sidebar
            user={user}
            collapsed={collapsed}
            onToggle={toggleCollapsed}
            onSearch={() => setPaletteOpen(true)}
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
          <LogoMark />
          <p className="text-[13px] font-semibold">LeadFinder</p>
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="ml-auto rounded p-1.5 text-fg-muted hover:bg-surface-hover"
            aria-label="Search"
          >
            <Search className="h-4 w-4" />
          </button>
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
                onSearch={() => {
                  setMobileOpen(false);
                  setPaletteOpen(true);
                }}
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
            "min-w-0 flex-1 px-4 pb-16 pt-16 transition-[margin] duration-200 ease-out md:px-8 md:pt-8",
            collapsed ? "md:ml-14" : "md:ml-[232px]",
          )}
        >
          <div className="mx-auto max-w-[1320px]">{children}</div>
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={commands} />
    </AuthContext.Provider>
  );
}
