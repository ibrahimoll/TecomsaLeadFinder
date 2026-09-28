import Link from "next/link";

import { Badge, EmptyState } from "@/components/ui";
import { ACTIVITY_LABEL } from "@/lib/constants";
import { formatDateTime } from "@/lib/format";
import type { Activity } from "@/types";

export function ActivityList({ items, emptyText }: { items: Activity[]; emptyText?: string }) {
  if (items.length === 0) {
    return <EmptyState title={emptyText ?? "No activity yet"} />;
  }
  return (
    <ul className="divide-y divide-slate-100">
      {items.map((a) => (
        <li key={a.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2.5">
          <Badge tone={a.activity_type === "NOTE_ADDED" ? "amber" : "gray"}>{ACTIVITY_LABEL[a.activity_type]}</Badge>
          <div className="min-w-0 flex-1">
            <p className="whitespace-pre-line break-words text-sm text-slate-800">{a.notes}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              {a.user?.name ?? "System"} · {formatDateTime(a.created_at)}
              {a.company && (
                <>
                  {" · "}
                  <Link className="text-brand-700 hover:underline" href={`/companies/${a.company.id}`}>
                    {a.company.name}
                  </Link>
                </>
              )}
              {a.campaign && (
                <>
                  {" · "}
                  <Link className="text-brand-700 hover:underline" href={`/campaigns/${a.campaign.id}`}>
                    {a.campaign.name}
                  </Link>
                </>
              )}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
