"use client";

import { PageHead } from "@/components/Shell";
import { BarList, ChartFrame, Donut, SERIES } from "@/components/charts";
import { Badge, Card, DataTable, ErrorNote, StatCard, StatusBadge } from "@/components/ui";
import { brain } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { inr, inrExact, num, pct, titleCase, toneFor } from "@/lib/format";

const RECOVERY_NOTE: Record<string, string> = {
  pending_settlements: "Razorpay settles on the normal cycle; 90% lands inside 48h.",
  overdue_receivables: "Collectable by dunning; historical collection rate applies.",
  disputes: "Chargeback outcomes are slow and mostly out of your hands.",
  failed_recovery: "Retryable failures from the last 48h.",
  pending_refunds: "Committed outflow — leaves the account, never returns.",
  scheduled_payouts: "Committed outflow — delayable, not recoverable.",
};

export default function MoneyPage() {
  const money = useResource(() => brain.money(), []);
  const analytics = useResource(() => brain.analytics(30), []);
  const state = useResource(() => brain.state(), []);

  const buckets: any[] = money.data?.buckets || [];
  const inflow = buckets.filter((b) => b.recoverable > 0);
  const outflow = buckets.filter((b) => b.recoverable === 0);
  const total = Number(money.data?.total_paise || 0);
  const recoverable = Number(money.data?.recoverable_48h_paise || 0);

  return (
    <>
      <PageHead
        title="Where is your money?"
        description="Every rupee that has left a customer but has not settled into usable cash, plus what is already committed to leave."
        actions={
          <button className="btn ghost sm" onClick={() => Promise.all([money.reload(), analytics.reload(), state.reload()])}>
            Refresh
          </button>
        }
      />
      <ErrorNote>{money.error || analytics.error}</ErrorNote>

      <div className="grid g4">
        <StatCard label="Total unresolved" value={inr(total)} foot={`${buckets.length} buckets`} />
        <StatCard
          label="Recoverable in 48h"
          value={inr(recoverable)}
          tone="good"
          foot={total ? `${pct(recoverable / total, 0)} of unresolved` : undefined}
        />
        <StatCard
          label="Committed outflows"
          value={inr(outflow.reduce((sum, b) => sum + b.amount_paise, 0))}
          tone="serious"
          foot="Payouts and refunds already promised"
        />
        <StatCard
          label="Cash after 24h"
          value={inr(state.data?.projected_cash_24h_paise)}
          foot={`Reserve floor ${inr(state.data?.cash_reserve_minimum_paise)}`}
        />
      </div>

      <div className="grid split">
        <ChartFrame
          title="Unresolved money by bucket"
          subtitle="Sized by amount; the recovery multiplier is the merchant's own historical rate."
          stale={money.refreshing}
          table={{
            columns: ["Bucket", "Amount", "Recovery rate", "Expected in 48h"],
            rows: buckets.map((b) => [
              b.label,
              inrExact(b.amount_paise),
              pct(b.recoverable, 0),
              inrExact(Math.round(b.amount_paise * b.recoverable)),
            ]),
          }}
        >
          <BarList
            items={buckets.map((b) => ({ key: b.key, label: b.label, value: b.amount_paise }))}
            format={inr}
            meta={(item) => {
              const bucket = buckets.find((b) => b.key === item.key);
              return bucket?.recoverable ? (
                <Badge tone="good">{pct(bucket.recoverable, 0)} recoverable</Badge>
              ) : (
                <Badge tone="neutral">committed</Badge>
              );
            }}
          />
        </ChartFrame>

        <ChartFrame
          title="Composition"
          subtitle="Share of unresolved money by bucket."
          stale={money.refreshing}
          table={{
            columns: ["Bucket", "Amount", "Share"],
            rows: buckets.map((b) => [b.label, inrExact(b.amount_paise), total ? pct(b.amount_paise / total, 1) : "—"]),
          }}
        >
          <Donut
            slices={buckets.map((b) => ({ key: b.key, label: b.label, value: b.amount_paise }))}
            format={inr}
          />
        </ChartFrame>
      </div>

      <Card
        title="Bucket detail"
        subtitle="What each bucket means, and what the brain expects to recover from it."
        stale={money.refreshing}
      >
        <DataTable
          rowKey={(row: any) => row.key}
          rows={buckets}
          columns={[
            { key: "label", header: "Bucket" },
            {
              key: "amount_paise",
              header: "Amount",
              align: "right",
              render: (row: any) => <strong>{inrExact(row.amount_paise)}</strong>,
            },
            {
              key: "recoverable",
              header: "Recovery rate",
              align: "right",
              render: (row: any) => pct(row.recoverable, 0),
            },
            {
              key: "expected",
              header: "Expected in 48h",
              align: "right",
              render: (row: any) => inrExact(Math.round(row.amount_paise * row.recoverable)),
            },
            {
              key: "note",
              header: "Why",
              render: (row: any) => <span className="tiny">{RECOVERY_NOTE[row.key] || "—"}</span>,
            },
          ]}
        />
      </Card>

      <div className="grid g2">
        <Card title="Settlements" subtitle="Batch status straight from the settlements collection." stale={analytics.refreshing}>
          <StatusList rows={analytics.data?.settlements || []} />
        </Card>
        <Card title="Payouts" subtitle="Vendor payouts by status." stale={analytics.refreshing}>
          <StatusList rows={analytics.data?.payouts || []} />
        </Card>
        <Card title="Invoices" subtitle="Receivables by status." stale={analytics.refreshing}>
          <StatusList rows={analytics.data?.invoices || []} />
        </Card>
        <Card title="Disputes & refunds" subtitle="Money at risk of leaving." stale={analytics.refreshing}>
          <StatusList rows={[...(analytics.data?.disputes || []), ...(analytics.data?.refunds || [])]} />
        </Card>
      </div>
    </>
  );
}

function StatusList({ rows }: { rows: any[] }) {
  if (!rows.length) return <p className="tiny">No records.</p>;
  return (
    <div className="rowlist">
      {rows.map((row, index) => (
        <div key={`${row.key}-${index}`}>
          <span className="row tight">
            <StatusBadge value={row.key} />
            <span className="tiny">{num(row.count)} records</span>
          </span>
          <strong className="num">{inr(row.amount_paise)}</strong>
        </div>
      ))}
    </div>
  );
}
