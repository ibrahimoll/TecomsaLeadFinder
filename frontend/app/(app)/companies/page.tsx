"use client";

import Link from "next/link";
import { useState } from "react";

import { OdooStatusBadge } from "@/components/status-badges";
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
import { countryNames, INDUSTRIES } from "@/lib/constants";
import { dash, formatDate } from "@/lib/format";
import type { Company, Page } from "@/types";

const PAGE_SIZE = 25;

export default function CompaniesPage() {
  const [q, setQ] = useState("");
  const [country, setCountry] = useState("");
  const [industry, setIndustry] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, loading } = useApi<Page<Company>>("/companies", {
    q,
    country,
    industry,
    page,
    page_size: PAGE_SIZE,
  });
  const filtered = Boolean(q || country || industry);

  return (
    <>
      <PageHeader
        title="Companies"
        description="The shared TECOMSA master company database."
        actions={<ButtonLink href="/companies/new">Add company</ButtonLink>}
      />
      <Card bodyClassName="p-0">
        <div className="flex flex-wrap gap-2 border-b border-slate-200 p-3">
          <Input
            className="max-w-xs"
            placeholder="Search name, domain or city…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
          <Select
            className="w-48"
            value={country}
            onChange={(e) => {
              setCountry(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All countries</option>
            {countryNames().map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
          <Select
            className="w-48"
            value={industry}
            onChange={(e) => {
              setIndustry(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All industries</option>
            {INDUSTRIES.map((i) => (
              <option key={i} value={i}>
                {i}
              </option>
            ))}
          </Select>
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
            title={filtered ? "No companies match your search" : "No companies yet"}
            description={filtered ? undefined : "Add companies manually to start building the database."}
            action={!filtered && <ButtonLink href="/companies/new">Add company</ButtonLink>}
          />
        ) : (
          data && (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>Company name</Th>
                    <Th>Country</Th>
                    <Th>Industry</Th>
                    <Th>Website</Th>
                    <Th>Main phone</Th>
                    <Th>Odoo status</Th>
                    <Th>Created</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.items.map((c) => (
                    <tr key={c.id} className="hover:bg-slate-50">
                      <Td>
                        <Link href={`/companies/${c.id}`} className="font-medium text-brand-700 hover:underline">
                          {c.name}
                        </Link>
                      </Td>
                      <Td>{dash(c.country)}</Td>
                      <Td>{dash(c.industry)}</Td>
                      <Td>
                        {c.website ? (
                          <a href={c.website} target="_blank" rel="noopener noreferrer" className="text-slate-700 hover:underline">
                            {c.domain ?? c.website}
                          </a>
                        ) : (
                          "—"
                        )}
                      </Td>
                      <Td>{dash(c.main_phone)}</Td>
                      <Td>
                        <OdooStatusBadge status={c.odoo_status} />
                      </Td>
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
    </>
  );
}
