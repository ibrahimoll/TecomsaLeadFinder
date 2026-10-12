"use client";

import { Select } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { Page, User } from "@/types";

/** The users a company can belong to (managers / admins only: pass enabled=false for a salesperson). */
export function useUsers(enabled: boolean): User[] {
  // ponytail: first 100 users only; page through /users if the team grows past that
  const { data } = useApi<Page<User>>(enabled ? "/users" : null, { page_size: 100 });
  return data?.items ?? [];
}

/** A user picker: `allLabel` is the empty choice ("All lead generators", "Unassigned"). */
export function OwnerSelect({ users, value, onChange, allLabel, className, disabled }: {
  users: User[];
  value: string;
  onChange: (value: string) => void;
  allLabel: string;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <Select aria-label="Lead generator" value={value} onChange={(e) => onChange(e.target.value)} className={className} disabled={disabled}>
      <option value="">{allLabel}</option>
      {users.map((u) => (
        <option key={u.id} value={String(u.id)}>
          {u.name}
        </option>
      ))}
    </Select>
  );
}
