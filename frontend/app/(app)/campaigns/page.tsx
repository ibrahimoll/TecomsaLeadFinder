"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { CampaignStatusBadge, DivisionBadge } from "@/components/status-badges";
import {
  Alert,
  ButtonLink,
  Card,
  EmptyState,
  Input,
  Loading,
  PageHeader,
  Pagination,
  Select,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { useApi } from "@/lib/api";
import { CAMPAIGN_STATUS_LABEL, DIVISIONS } from "@/lib/constants";
import { dash, formatDate } from "@/lib/format";
import type { Campaign, CampaignStatus, Page } from "@/types";

const PAGE_SIZE = 25;

function CampaignsTable() {
  const router = useRouter();
  const params = useSearchParams();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const status = params.get("status") ?? "";
  const division = params.get("division") ?? "";
  const mine = params.get("mine") === "1";

  const { data, error, loading } = useApi<Page<Campaign>>("/campaigns", {
    q,
    status,
    division,
    mine: mine || undefined,
    page,
    page_size: PAGE_SIZE,
  });

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    setPage(1);
    router.replace(`/campaigns${next.toString() ? `?${next}` : ""}`);
  }

  const filtered = Boolean(q || status || division || mine);

  return (
    <Card bodyClassName="p-0">
      <div className="flex flex-wrap gap-2 border-b border-slate-200 p-3">
        <Input
          className="max-w-xs"
          placeholder="Search campaign name…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
        <Select className="w-40" value={division} onChange={(e) => setFilter("division", e.target.value)}>
          <option value="">All divisions</option>
          {DIVISIONS.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </Select>
        <Select className="w-40" value={status} onChange={(e) => setFilter("status", e.target.value)}>
          <option value="">All statuses</option>
          {(Object.keys(CAMPAIGN_STATUS_LABEL) as CampaignStatus[]).map((s) => (
            <option key={s} value={s}>
              {CAMPAIGN_STATUS_LABEL[s]}
            </option>
          ))}
        </Select>
        <label className="flex items-center gap-1.5 text-sm text-slate-600">
          <input type="checkbox" checked={mine} onChange={(e) => setFilter("mine", e.target.checked ? "1" : "")} />
          Created by me
        </label>
      </div>
      {error && (
        <div className="p-3">
          <Alert>{error.message}</Alert>
        </div>
      )}
      {loading && !data ? (
        <Loading />
      ) : data && data.items.length === 0 ? (
        <EmptyState
          title={filtered ? "No campaigns match these filters" : "No campaigns yet"}
          description={filtered ? undefined : "Create a campaign draft to define who TECOMSA should target."}
          action={!filtered && <ButtonLink href="/campaigns/new">Create campaign</ButtonLink>}
        />
      ) : (
        data && (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Campaign name</Th>
                  <Th>Division</Th>
                  <Th>Country</Th>
                  <Th>Industry</Th>
                  <Th className="text-right">Target</Th>
                  <Th>Status</Th>
                  <Th>Creator</Th>
                  <Th>Created</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((c) => (
                  <tr key={c.id} className="hover:bg-slate-50">
                    <Td>
                      <Link href={`/campaigns/${c.id}`} className="font-medium text-brand-700 hover:underline">
                        {c.name}
                      </Link>
                    </Td>
                    <Td>
                      <DivisionBadge division={c.tecomsa_division} />
                    </Td>
                    <Td>{c.country}</Td>
                    <Td>{dash(c.industry)}</Td>
                    <Td className="text-right tabular-nums">
                      {c.company_count} / {c.target_company_count}
                    </Td>
                    <Td>
                      <CampaignStatusBadge status={c.status} />
                    </Td>
                    <Td>{c.creator.name}</Td>
                    <Td>{formatDate(c.created_at)}</Td>
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

export default function CampaignsPage() {
  return (
    <>
      <PageHeader
        title="Campaigns"
        description="Prospecting campaigns by TECOMSA division."
        actions={<ButtonLink href="/campaigns/new">Create campaign</ButtonLink>}
      />
      <Suspense fallback={<Loading />}>
        <CampaignsTable />
      </Suspense>
    </>
  );
}
