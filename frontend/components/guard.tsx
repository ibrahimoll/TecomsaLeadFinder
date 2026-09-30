"use client";

import { Lock } from "lucide-react";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui";
import { useCurrentUser } from "@/lib/auth";
import type { Capabilities } from "@/types";

/** UI convenience only: the backend independently rejects unauthorised requests. */
export function RequireCapability({ capability, children }: { capability: keyof Capabilities; children: ReactNode }) {
  const user = useCurrentUser();
  if (!user.capabilities[capability]) {
    return (
      <div className="rounded-lg border border-border bg-surface">
        <EmptyState
          icon={<Lock className="h-5 w-5" />}
          title="You don't have access to this page"
          description="Ask a LeadFinder administrator if you need access."
        />
      </div>
    );
  }
  return <>{children}</>;
}
