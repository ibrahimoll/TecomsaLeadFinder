"use client";

import type { ReactNode } from "react";

import { Alert } from "@/components/ui";
import { useCurrentUser } from "@/lib/auth";

/** UI convenience only - the backend independently rejects non-admin requests. */
export function AdminGuard({ children }: { children: ReactNode }) {
  const user = useCurrentUser();
  if (user.role !== "ADMIN") return <Alert>Administration is available to administrators only.</Alert>;
  return <>{children}</>;
}
