"use client";

import { useState } from "react";

import { ActivityList } from "@/components/activity-list";
import { ErrorState, PageHeader, Pagination, Section, Select } from "@/components/ui";
import { useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import type { Activity, Page } from "@/types";

const PAGE_SIZE = 30;

export default function ActivityPage() {
  const user = useCurrentUser();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useApi<Page<Activity>>("/activities", { scope, page, page_size: PAGE_SIZE });

  return (
    <>
      <PageHeader
        title={scope === "mine" ? "My activity" : "Team activity"}
        description="Prospecting events recorded in LeadFinder, newest first."
        actions={
          isPrivileged(user) && (
            <Select
              aria-label="Whose activity"
              className="w-40"
              value={scope}
              onChange={(e) => {
                setScope(e.target.value as "mine" | "all");
                setPage(1);
              }}
            >
              <option value="mine">My activity</option>
              <option value="all">Whole team</option>
            </Select>
          )
        }
      />
      <Section flush>
        {error ? (
          <ErrorState message={error.message} onRetry={reload} />
        ) : (
          <>
            <div className="p-4">
              <ActivityList items={data?.items} loading={loading} />
            </div>
            {data && (
              <div className="border-t border-border">
                <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
              </div>
            )}
          </>
        )}
      </Section>
    </>
  );
}
