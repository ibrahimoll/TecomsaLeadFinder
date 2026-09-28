"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert, Button, Card, Field, Input, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth";
import { USER_ROLES } from "@/lib/constants";
import type { User, UserRole } from "@/types";

export function UserForm({ user }: { user?: User }) {
  const router = useRouter();
  const me = useCurrentUser();
  const isSelf = user?.id === me.id;
  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [role, setRole] = useState<UserRole>(user?.role ?? "SALES_AGENT");
  const [odooUserId, setOdooUserId] = useState(user?.odoo_user_id != null ? String(user.odoo_user_id) : "");
  const [password, setPassword] = useState("");
  const [isActive, setIsActive] = useState(user?.is_active ?? true);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setErrors({});
    setFormError(null);
    const body: Record<string, unknown> = {
      name,
      email,
      role,
      odoo_user_id: odooUserId === "" ? null : Number(odooUserId),
      is_active: isActive,
    };
    if (password) body.password = password;
    try {
      if (user) await api(`/users/${user.id}`, { method: "PATCH", body });
      else await api("/users", { method: "POST", body });
      router.push("/admin");
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors);
        setFormError(err.message);
      }
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit}>
      <Card>
        <div className="space-y-4">
          {formError && <Alert>{formError}</Alert>}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field label="Full name" htmlFor="name" required error={errors.name}>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
            </Field>
            <Field label="Email" htmlFor="email" required error={errors.email}>
              <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required maxLength={320} />
            </Field>
            <Field label="Role" htmlFor="role" required error={errors.role} hint={isSelf ? "You cannot change your own role." : undefined}>
              <Select id="role" value={role} onChange={(e) => setRole(e.target.value as UserRole)} disabled={isSelf}>
                {USER_ROLES.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Odoo user ID" htmlFor="odoo_user_id" error={errors.odoo_user_id} hint="Optional. Links this account to the user's TECOMSA Odoo user in a later phase.">
              <Input id="odoo_user_id" type="number" min={1} value={odooUserId} onChange={(e) => setOdooUserId(e.target.value)} />
            </Field>
            <Field
              label={user ? "New password" : "Password"}
              htmlFor="password"
              required={!user}
              error={errors.password}
              hint={user ? "Leave blank to keep the current password. Changing it signs the user out everywhere." : "At least 10 characters."}
            >
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required={!user}
                minLength={10}
                maxLength={256}
              />
            </Field>
            <Field label="Status" htmlFor="is_active" error={errors.is_active}>
              <label className="flex items-center gap-2 py-1.5 text-sm">
                <input id="is_active" type="checkbox" checked={isActive} disabled={isSelf} onChange={(e) => setIsActive(e.target.checked)} />
                Active (can sign in)
              </label>
            </Field>
          </div>
          <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
            <Button type="button" variant="secondary" onClick={() => router.push("/admin")}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? "Saving…" : user ? "Save changes" : "Create user"}
            </Button>
          </div>
        </div>
      </Card>
    </form>
  );
}
