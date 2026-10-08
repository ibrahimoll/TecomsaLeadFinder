import clsx from "clsx";
import { Building2, Megaphone, StickyNote, UserPlus, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState, Skeleton } from "@/components/ui";
import type { Activity, ActivityType } from "@/types";

const ICON: Record<ActivityType, LucideIcon> = {
  COMPANY_CREATED: Building2,
  CAMPAIGN_CREATED: Megaphone,
  COMPANY_ADDED_TO_CAMPAIGN: Megaphone,
  CONTACT_ADDED: UserPlus,
  NOTE_ADDED: StickyNote,
};

function CompanyLink({ a }: { a: Activity }) {
  return a.company ? (
    <Link className="font-medium hover:underline" href={`/companies/${a.company.id}`}>
      {a.company.name}
    </Link>
  ) : null;
}

function CampaignLink({ a }: { a: Activity }) {
  return a.campaign ? (
    <Link className="font-medium hover:underline" href={`/campaigns/${a.campaign.id}`}>
      {a.campaign.name}
    </Link>
  ) : null;
}

/** "Nadine added ABC Foods to Pharma push": one readable sentence per event. */
function Sentence({ a }: { a: Activity }) {
  const m = (text: string) => <span className="text-fg-muted">{text}</span>;
  switch (a.activity_type) {
    case "COMPANY_CREATED":
      return <>{m("added ")}<CompanyLink a={a} /></>;
    case "CAMPAIGN_CREATED":
      return <>{m("created campaign ")}<CampaignLink a={a} /></>;
    case "COMPANY_ADDED_TO_CAMPAIGN":
      return <>{m("added ")}<CompanyLink a={a} />{m(" to ")}<CampaignLink a={a} /></>;
    case "CONTACT_ADDED":
      return <>{m("added ")}{a.contact?.full_name ?? "a contact"}{a.company && <>{m(" at ")}<CompanyLink a={a} /></>}</>;
    case "NOTE_ADDED":
      return <>{m("left a note")}{a.company && <>{m(" on ")}<CompanyLink a={a} /></>}</>;
  }
}

const time = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });
const day = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "2-digit", month: "short" });

function dayLabel(date: Date): string {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "Today";
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return day.format(date);
}

/** Activity timeline grouped by day (pattern adapted from 21st.dev "Activity Timeline"). */
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
      <div className="space-y-4 py-1">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex gap-3">
            <Skeleton className="h-6 w-6 rounded-full" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-1/3" />
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (!items || items.length === 0) return <EmptyState compact title={emptyText} />;

  const groups: { label: string; items: Activity[] }[] = [];
  for (const a of items) {
    const label = dayLabel(new Date(a.created_at));
    const last = groups[groups.length - 1];
    if (last?.label === label) last.items.push(a);
    else groups.push({ label, items: [a] });
  }

  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <section key={group.label}>
          <h3 className="mb-2 text-[11px] font-medium text-fg-subtle">{group.label}</h3>
          <ol className="relative">
            {group.items.map((a, i) => {
              const Icon = ICON[a.activity_type];
              return (
                <li key={a.id} className="relative flex gap-3 pb-3.5 last:pb-0">
                  {i < group.items.length - 1 && <span className="absolute left-[11.5px] top-7 h-[calc(100%-22px)] w-px bg-border" aria-hidden />}
                  <span
                    className={clsx(
                      "relative z-[1] mt-px flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-surface",
                      a.activity_type === "NOTE_ADDED" ? "text-warning" : "text-fg-subtle",
                    )}
                    aria-hidden
                  >
                    <Icon className="h-3 w-3" strokeWidth={2} />
                  </span>
                  <div className="min-w-0 flex-1 text-[13px] leading-5">
                    <p className="text-fg">
                      <span className="font-medium">{a.user?.name ?? "System"}</span> <Sentence a={a} />
                    </p>
                    {a.notes && a.activity_type === "NOTE_ADDED" && (
                      <p className="mt-1 whitespace-pre-line break-words rounded border border-border bg-surface-muted/50 px-2.5 py-1.5 text-fg">
                        {a.notes}
                      </p>
                    )}
                    <time dateTime={a.created_at} className="text-[11.5px] tabular text-fg-subtle">
                      {time.format(new Date(a.created_at))}
                    </time>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
