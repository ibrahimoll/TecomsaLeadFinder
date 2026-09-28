"use client";

import { useState } from "react";

import { ActivityList } from "@/components/activity-list";
import { Alert, Card, Loading, PageHeader, Pagination, Select } from "@/components/ui";
import { useApi } from "@/lib/api";
import { isPrivileged, useCurrentUser } from "@/lib/auth";
import type { Activity, Page } from "@/types";

const PAGE_SIZE = 30;

export default function ActivityPage() {
  const user = useCurrentUser();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [page, setPage] = useState(1);
  const { data, error, loading } = useApi<Page<Activity>>("/activities", { scope, page, page_size: PAGE_SIZE });

  return (
    <>
      <PageHeader
        title={scope === "mine" ? "My activity" : "Team activity"}
        description="Recorded prospecting events, newest first."
        actions={
          isPrivileged(user) && (
            <Select
              value={scope}
              onChange={(e) => {
                setScope(e.target.value as "mine" | "all");
                setPage(1);
              }}
              aria-label="Activity scope"
            >
              <option value="mine">My activity</option>
              <option value="all">Whole team</option>
            </Select>
          )
        }
      />
      {error && <Alert>{error.message}</Alert>}
      <Card bodyClassName="p-0">
        {loading && !data ? (
          <Loading />
        ) : (
          <>
            <div className="px-4 py-1">
              <ActivityList items={data?.items ?? []} emptyText="No activity recorded yet" />
            </div>
            {data && <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />}
          </>
        )}
      </Card>
    </>
  );
}
