"use client";

import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";

import { AdminGuard } from "@/components/admin-guard";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  Input,
  Loading,
  PageHeader,
  Pagination,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth";
import { ROLE_LABEL } from "@/lib/constants";
import { dash, formatDateTime } from "@/lib/format";
import type { AuditLog, Page, SystemStatus, User } from "@/types";

const PAGE_SIZE = 25;

function UsersTab() {
  const me = useCurrentUser();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [actionError, setActionError] = useState<string | null>(null);
  const { data, error, loading, reload } = useApi<Page<User>>("/users", { q, page, page_size: PAGE_SIZE });

  async function toggleActive(user: User) {
    setActionError(null);
    try {
      await api(`/users/${user.id}`, { method: "PATCH", body: { is_active: !user.is_active } });
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not update user.");
    }
  }

  return (
    <Card
      bodyClassName="p-0"
      title="Users"
      actions={<ButtonLink href="/admin/users/new">Create user</ButtonLink>}
    >
      <div className="border-b border-slate-200 p-3">
        <Input
          className="max-w-xs"
          placeholder="Search name or email…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
      </div>
      {(error || actionError) && (
        <div className="p-3">
          <Alert>{error?.message ?? actionError}</Alert>
        </div>
      )}
      {loading && !data ? (
        <Loading />
      ) : data && data.items.length === 0 ? (
        <EmptyState title="No users found" />
      ) : (
        data && (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Email</Th>
                  <Th>Role</Th>
                  <Th>Odoo user</Th>
                  <Th>Status</Th>
                  <Th>Last login</Th>
                  <Th />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((u) => (
                  <tr key={u.id} className="hover:bg-slate-50">
                    <Td>
                      <Link href={`/admin/users/${u.id}`} className="font-medium text-brand-700 hover:underline">
                        {u.name}
                      </Link>
                    </Td>
                    <Td>{u.email}</Td>
                    <Td>{ROLE_LABEL[u.role]}</Td>
                    <Td>{u.odoo_user_id ?? <span className="text-slate-400">Not linked</span>}</Td>
                    <Td>{u.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="red">Inactive</Badge>}</Td>
                    <Td>{formatDateTime(u.last_login_at)}</Td>
                    <Td className="text-right">
                      {u.id !== me.id && (
                        <Button variant={u.is_active ? "danger" : "secondary"} onClick={() => toggleActive(u)}>
                          {u.is_active ? "Deactivate" : "Activate"}
                        </Button>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          </>
        )
      )}
    </Card>
  );
}

function AuditTab() {
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, loading } = useApi<Page<AuditLog>>("/audit", { action, page, page_size: PAGE_SIZE });

  return (
    <Card title="Audit log" bodyClassName="p-0">
      <div className="border-b border-slate-200 p-3">
        <Input
          className="max-w-xs"
          placeholder="Filter by action, e.g. company.created"
          value={action}
          onChange={(e) => {
            setAction(e.target.value.trim());
            setPage(1);
          }}
        />
      </div>
      {error && (
        <div className="p-3">
          <Alert>{error.message}</Alert>
        </div>
      )}
      {loading && !data ? (
        <Loading />
      ) : data && data.items.length === 0 ? (
        <EmptyState title="No audit records" />
      ) : (
        data && (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Time</Th>
                  <Th>User</Th>
                  <Th>Action</Th>
                  <Th>Entity</Th>
                  <Th>Details</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((a) => (
                  <tr key={a.id}>
                    <Td>{formatDateTime(a.created_at)}</Td>
                    <Td>{a.user?.name ?? <span className="text-slate-400">—</span>}</Td>
                    <Td>
                      <code className="text-xs">{a.action}</code>
                    </Td>
                    <Td>{a.entity_type ? `${a.entity_type} #${dash(a.entity_id)}` : "—"}</Td>
                    <Td className="max-w-md whitespace-normal">
                      <code className="break-all text-xs text-slate-600">{a.metadata ? JSON.stringify(a.metadata) : "—"}</code>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          </>
        )
      )}
    </Card>
  );
}

function SettingsTab() {
  const { data, error, loading } = useApi<SystemStatus>("/settings/status");
  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error.message}</Alert>;
  if (!data) return null;
  return (
    <Card title="Application status">
      <p className="mb-4 text-sm text-slate-600">
        Version {data.version} · Environment <code>{data.environment}</code>
      </p>
      <Table>
        <thead>
          <tr>
            <Th>Integration</Th>
            <Th>Status</Th>
            <Th>Notes</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {data.integrations.map((i) => (
            <tr key={i.name}>
              <Td>{i.name}</Td>
              <Td>
                <Badge tone="gray">{i.status === "DISCONNECTED" ? "Not connected" : i.status}</Badge>
              </Td>
              <Td className="whitespace-normal">{i.detail}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

const TABS = [
  { key: "users", label: "Users" },
  { key: "audit", label: "Audit log" },
  { key: "settings", label: "Settings" },
] as const;

export default function AdminPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("users");
  return (
    <AdminGuard>
      <PageHeader title="Administration" description="Manage LeadFinder users and review the audit trail." />
      <div className="mb-4 flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={clsx(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium",
              tab === t.key ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "users" && <UsersTab />}
      {tab === "audit" && <AuditTab />}
      {tab === "settings" && <SettingsTab />}
    </AdminGuard>
  );
}
