import clsx from "clsx";
import { Building2, FileText, Megaphone, StickyNote, UserPlus } from "lucide-react";
import Link from "next/link";

import { EmptyState, Skeleton } from "@/components/ui";
import { ACTIVITY_LABEL } from "@/lib/constants";
import { formatDateTime } from "@/lib/format";
import type { Activity, ActivityType } from "@/types";

const ICON: Record<ActivityType, typeof FileText> = {
  COMPANY_CREATED: Building2,
  CAMPAIGN_CREATED: Megaphone,
  COMPANY_ADDED_TO_CAMPAIGN: Megaphone,
  CONTACT_ADDED: UserPlus,
  NOTE_ADDED: StickyNote,
};

/** Vertical timeline of activity events. */
export function ActivityList({
  items,
  loading,
  emptyText = "No activity recorded yet",
}: {
  items: Activity[] | undefined;
  loading?: boolean;
  emptyText?: string;
}) {
  if (loading && !items) {
    return (
      <div className="space-y-3 py-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    );
  }
  if (!items || items.length === 0) return <EmptyState compact title={emptyText} />;

  return (
    <ol className="relative">
      {items.map((a, i) => {
        const Icon = ICON[a.activity_type];
        return (
          <li key={a.id} className="relative flex gap-3 pb-4 last:pb-0">
            {i < items.length - 1 && <span className="absolute left-[11px] top-6 h-[calc(100%-18px)] w-px bg-border" aria-hidden />}
            <span
              className={clsx(
                "relative z-[1] mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-surface",
                a.activity_type === "NOTE_ADDED" ? "text-warning" : "text-fg-subtle",
              )}
              aria-hidden
            >
              <Icon className="h-3 w-3" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] text-fg">
                <span className="font-medium">{a.user?.name ?? "System"}</span>{" "}
                <span className="text-fg-muted">· {ACTIVITY_LABEL[a.activity_type].toLowerCase()}</span>
              </p>
              {a.notes && <p className="mt-0.5 whitespace-pre-line break-words text-[13px] text-fg">{a.notes}</p>}
              <p className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-fg-muted">
                <time dateTime={a.created_at}>{formatDateTime(a.created_at)}</time>
                {a.company && (
                  <Link className="hover:text-accent hover:underline" href={`/companies/${a.company.id}`}>
                    {a.company.name}
                  </Link>
                )}
                {a.campaign && (
                  <Link className="hover:text-accent hover:underline" href={`/campaigns/${a.campaign.id}`}>
                    {a.campaign.name}
                  </Link>
                )}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
