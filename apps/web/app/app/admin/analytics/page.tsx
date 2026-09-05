"use client";

import { useState } from "react";
import { PageHead } from "@/components/Shell";
import { BarList, ChartFrame, Donut, LineChart, SERIES, Scatter, StackedBars } from "@/components/charts";
import { Badge, Card, DataTable, ErrorNote, Segmented, Skeleton, StatCard, StatusBadge } from "@/components/ui";
import { brain } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { dateTime, inr, inrExact, num, pct, shortDate, timeOfDay, titleCase, toneFor } from "@/lib/format";

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const analytics = useResource(() => brain.analytics(days), [days]);

  const d = analytics.data;
  const head = d?.headline || {};
  const payments: any[] = d?.payments_daily || [];
  const methods: any[] = d?.method_breakdown || [];
  const channels: any[] = d?.channel_breakdown || [];
  const funnel: any[] = d?.funnel || [];
  const money = d?.unresolved_money || {};
  const actions = d?.actions || {};
  const outcomes = d?.outcomes || {};
  const agents: any[] = d?.agents || [];
  const events = d?.events || {};
  const stateHistory: any[] = d?.state_history || [];
  const totals = d?.totals || {};
  const topCustomers: any[] = d?.top_customers || [];

  return (
    <>
      <PageHead
        title="Analytics"
        description="Every roll-up is computed from the same collections the agents read — there is no separate reporting store."
        actions={
          <>
            {/* One filter row above everything it scopes; never a per-chart filter. */}
            <Segmented
              label="Range"
              value={days}
              onChange={setDays}
              options={[
                { value: 7, label: "7d" },
                { value: 14, label: "14d" },
                { value: 30, label: "30d" },
                { value: 60, label: "60d" },
                { value: 90, label: "90d" },
              ]}
            />
            <button className="btn ghost sm" onClick={analytics.reload} disabled={analytics.refreshing}>
              {analytics.refreshing ? "Refreshing…" : "Refresh"}
            </button>
          </>
        }
      />
      <ErrorNote>{analytics.error}</ErrorNote>
      {d?.generated_at && (
        <p className="tiny">
          Generated {dateTime(d.generated_at)} · window {d.range_days} days · merchant{" "}
          <span className="mono">{d.merchant_id}</span>
        </p>
      )}

      {analytics.loading ? (
        <div className="grid g4">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <Skeleton key={i} height={104} />
          ))}
        </div>
      ) : (
        <div className="grid g4">
          <StatCard label={`GMV captured (${days}d)`} value={inr(head.gmv_paise)} foot={`${num(head.captured_count)} payments`} />
          <StatCard
            label="Success rate"
            value={pct(head.success_rate)}
            foot={`${num(head.failed_count)} failed · ${inr(head.failed_gmv_paise)} lost`}
            tone={head.success_rate > 0.95 ? "good" : head.success_rate > 0.9 ? "warning" : "critical"}
          />
          <StatCard label="Average order value" value={inr(head.average_order_value_paise)} foot="Captured payments only" />
          <StatCard label="Cash on hand" value={inr(head.cash_paise)} foot={`Projected 24h ${inr(head.projected_cash_24h_paise)}`} />
          <StatCard
            label="Reserve breach risk"
            value={pct(head.reserve_breach_probability)}
            tone={head.reserve_breach_probability > 0.35 ? "critical" : "good"}
          />
          <StatCard label="Operational risk" value={pct(head.operational_risk)} foot={<StatusBadge value={head.label} />} />
          <StatCard label="Unresolved money" value={inr(money.total_paise)} foot={`Recoverable ${inr(money.recoverable_48h_paise)}`} />
          <StatCard
            label="Action verification"
            value={pct(actions.verification_rate)}
            foot={`${num(actions.verified)} verified · ${num(actions.failed)} failed · ${num(actions.pending_approval)} pending`}
          />
        </div>
      )}

      <div className="grid split">
        <ChartFrame
          title="Payment volume"
          subtitle="Captured against failed rupee volume, per day."
          stale={analytics.refreshing}
          legend={[
            { key: "captured_paise", label: "Captured" },
            { key: "failed_paise", label: "Failed" },
          ]}
          table={{
            columns: ["Date", "Captured", "Failed", "Attempts", "Success rate"],
            rows: [...payments].reverse().map((p) => [
              p.date,
              inrExact(p.captured_paise),
              inrExact(p.failed_paise),
              num(p.attempts),
              p.success_rate === null ? "—" : pct(p.success_rate),
            ]),
          }}
        >
          <StackedBars
            points={payments}
            xKey="date"
            series={[
              { key: "captured_paise", label: "Captured" },
              { key: "failed_paise", label: "Failed" },
            ]}
            format={inr}
            xFormat={shortDate}
          />
        </ChartFrame>

        <ChartFrame
          title="Success and failure rate"
          subtitle="Share of attempts per day. One axis — rates only."
          stale={analytics.refreshing}
          legend={[
            { key: "success_rate", label: "Success rate" },
            { key: "failure_rate", label: "Failure rate" },
          ]}
          table={{
            columns: ["Date", "Success", "Failure", "Attempts"],
            rows: [...payments].reverse().map((p) => [
              p.date,
              p.success_rate === null ? "—" : pct(p.success_rate),
              p.failure_rate === null ? "—" : pct(p.failure_rate),
              num(p.attempts),
            ]),
          }}
        >
          <LineChart
            points={payments}
            xKey="date"
            series={[
              { key: "success_rate", label: "Success rate" },
              { key: "failure_rate", label: "Failure rate" },
            ]}
            format={(v) => pct(v, 0)}
            xFormat={shortDate}
          />
        </ChartFrame>
      </div>

      <div className="grid g3">
        <ChartFrame
          title="By payment method"
          subtitle="Captured volume; failure rate shown beside each."
          stale={analytics.refreshing}
          table={{
            columns: ["Method", "Captured GMV", "Attempts", "Failure rate"],
            rows: methods.map((m) => [titleCase(m.key), inrExact(m.gmv_paise), num(m.attempts), pct(m.failure_rate)]),
          }}
        >
          <BarList
            items={methods.map((m) => ({ key: m.key, label: titleCase(m.key), value: m.gmv_paise }))}
            format={inr}
            meta={(item) => {
              const method = methods.find((m) => m.key === item.key);
              return (
                <Badge tone={method.failure_rate > 0.08 ? "critical" : method.failure_rate > 0.05 ? "warning" : "good"}>
                  {pct(method.failure_rate)} fail
                </Badge>
              );
            }}
          />
        </ChartFrame>

        <ChartFrame
          title="By channel"
          subtitle="Where the volume originates."
          stale={analytics.refreshing}
          table={{
            columns: ["Channel", "Captured GMV", "Attempts", "Failure rate"],
            rows: channels.map((c) => [titleCase(c.key), inrExact(c.gmv_paise), num(c.attempts), pct(c.failure_rate)]),
          }}
        >
          <BarList
            items={channels.map((c) => ({ key: c.key, label: titleCase(c.key), value: c.gmv_paise }))}
            format={inr}
            color={SERIES[2]}
            meta={(item) => <span className="tiny">{num(channels.find((c) => c.key === item.key)?.attempts)} attempts</span>}
          />
        </ChartFrame>

        <ChartFrame
          title="Order to settlement funnel"
          subtitle="Ordered stages use the single-hue ordinal ramp."
          stale={analytics.refreshing}
          table={{
            columns: ["Stage", "Count", "Share of top"],
            rows: funnel.map((f) => [f.stage, num(f.value), pct(f.share, 0)]),
          }}
        >
          <BarList
            items={funnel.map((f) => ({ key: f.stage, label: f.stage, value: f.value }))}
            format={num}
            ordinal
            meta={(item) => <span className="tiny">{pct(funnel.find((f) => f.stage === item.key)?.share, 0)}</span>}
          />
        </ChartFrame>
      </div>

      <div className="grid split">
        <ChartFrame
          title="World state over time"
          subtitle="Cash against the reserve floor across every recomputed state."
          stale={analytics.refreshing}
          legend={[
            { key: "cash_paise", label: "Cash" },
            { key: "projected_cash_24h_paise", label: "Projected 24h" },
            { key: "cash_reserve_minimum_paise", label: "Reserve floor" },
          ]}
          table={{
            columns: ["Computed", "Cash", "Projected", "Reserve", "Label"],
            rows: [...stateHistory].reverse().slice(0, 40).map((p) => [
              dateTime(p.computed_at),
              inrExact(p.cash_paise),
              inrExact(p.projected_cash_24h_paise),
              inrExact(p.cash_reserve_minimum_paise),
              titleCase(p.label),
            ]),
          }}
        >
          <LineChart
            points={stateHistory}
            xKey="computed_at"
            series={[
              { key: "cash_paise", label: "Cash" },
              { key: "projected_cash_24h_paise", label: "Projected 24h" },
              { key: "cash_reserve_minimum_paise", label: "Reserve floor" },
            ]}
            format={inr}
            xFormat={timeOfDay}
          />
        </ChartFrame>

        <ChartFrame
          title="Risk over time"
          subtitle="Reserve breach probability, operational risk and 24h failure rate."
          stale={analytics.refreshing}
          legend={[
            { key: "reserve_breach_probability", label: "Reserve breach" },
            { key: "operational_risk", label: "Operational risk" },
            { key: "failure_rate_24h", label: "Failure rate 24h" },
          ]}
          table={{
            columns: ["Computed", "Breach", "Operational", "Failure 24h"],
            rows: [...stateHistory].reverse().slice(0, 40).map((p) => [
              dateTime(p.computed_at),
              pct(p.reserve_breach_probability),
              pct(p.operational_risk),
              pct(p.failure_rate_24h),
            ]),
          }}
        >
          <LineChart
            points={stateHistory}
            xKey="computed_at"
            series={[
              { key: "reserve_breach_probability", label: "Reserve breach" },
              { key: "operational_risk", label: "Operational risk" },
              { key: "failure_rate_24h", label: "Failure rate 24h" },
            ]}
            format={(v) => pct(v, 0)}
            xFormat={timeOfDay}
          />
        </ChartFrame>
      </div>

      <div className="grid split">
        <ChartFrame
          title="Unresolved money"
          subtitle="Share of money that has not reached usable cash."
          stale={analytics.refreshing}
          table={{
            columns: ["Bucket", "Amount", "Recovery rate"],
            rows: (money.buckets || []).map((b: any) => [b.label, inrExact(b.amount_paise), pct(b.recoverable, 0)]),
          }}
        >
          <Donut
            slices={(money.buckets || []).map((b: any) => ({ key: b.key, label: b.label, value: b.amount_paise }))}
            format={inr}
          />
        </ChartFrame>

        <ChartFrame
          title="Outcome calibration"
          subtitle="Predicted impact against measured impact. Points on the diagonal are perfectly calibrated."
          stale={analytics.refreshing}
          table={{
            columns: ["Action", "Agent", "Expected", "Actual", "Error"],
            rows: (outcomes.points || []).map((p: any) => [
              p.action_id,
              titleCase(p.agent_id),
              inrExact(p.expected_impact_paise),
              inrExact(p.actual_impact_paise),
              p.prediction_error === null ? "—" : pct(p.prediction_error),
            ]),
          }}
        >
          <Scatter
            points={(outcomes.points || []).map((p: any) => ({
              x: p.expected_impact_paise,
              y: p.actual_impact_paise,
              label: `${titleCase(p.agent_id)} · ${p.action_id}`,
              tone: p.result === "positive" ? SERIES[0] : SERIES[7],
            }))}
            format={inr}
            xLabel="Expected impact"
            yLabel="Actual impact"
          />
        </ChartFrame>
      </div>

      <div className="grid g3">
        <ChartFrame
          title="Actions by status"
          subtitle="The safety pipeline, end to end."
          stale={analytics.refreshing}
          table={{
            columns: ["Status", "Count", "Amount"],
            rows: (actions.by_status || []).map((s: any) => [titleCase(s.key), num(s.count), inrExact(s.amount_paise)]),
          }}
        >
          <BarList
            items={(actions.by_status || []).map((s: any) => ({ key: s.key, label: titleCase(s.key), value: s.count }))}
            format={num}
            meta={(item) => <span className="tiny">{inr((actions.by_status || []).find((s: any) => s.key === item.key)?.amount_paise)}</span>}
          />
        </ChartFrame>

        <ChartFrame
          title="Actions by type"
          subtitle="What the agents actually asked for."
          stale={analytics.refreshing}
          table={{
            columns: ["Type", "Count", "Amount"],
            rows: (actions.by_type || []).map((s: any) => [s.key, num(s.count), inrExact(s.amount_paise)]),
          }}
        >
          <BarList
            items={(actions.by_type || []).map((s: any) => ({ key: s.key, label: s.key, value: s.count }))}
            format={num}
            color={SERIES[1]}
          />
        </ChartFrame>

        <ChartFrame
          title="Events by type"
          subtitle={`${num(events.total)} events ingested in total.`}
          stale={analytics.refreshing}
          table={{
            columns: ["Event type", "Count"],
            rows: (events.by_type || []).map((e: any) => [e.key, num(e.count)]),
          }}
        >
          <BarList
            items={(events.by_type || []).map((e: any) => ({ key: e.key, label: e.key, value: e.count }))}
            format={num}
            color={SERIES[2]}
            maxRows={10}
          />
        </ChartFrame>
      </div>

      <ChartFrame
        title="Event ingestion volume"
        subtitle="Daily event count across every source."
        stale={analytics.refreshing}
        table={{
          columns: ["Date", "Events"],
          rows: [...(events.daily || [])].reverse().map((e: any) => [e.date, num(e.count)]),
        }}
      >
        <LineChart
          points={events.daily || []}
          xKey="date"
          series={[{ key: "count", label: "Events" }]}
          format={num}
          xFormat={shortDate}
          area
        />
      </ChartFrame>

      <div className="grid split">
        <Card title="Agent leaderboard" subtitle="Trust is earned per merchant from verified outcomes." stale={analytics.refreshing}>
          <DataTable
            rows={agents}
            rowKey={(row) => row.agent_id}
            columns={[
              { key: "agent_id", header: "Agent", render: (row) => <strong>{titleCase(row.agent_id)}</strong> },
              { key: "trust", header: "Trust", align: "right", render: (row) => pct(row.trust) },
              { key: "autonomy", header: "Autonomy", render: (row) => <Badge tone={toneFor(row.autonomy)}>{titleCase(row.autonomy)}</Badge> },
              { key: "proposals", header: "Proposals", align: "right" },
              { key: "actions", header: "Actions", align: "right" },
              { key: "outcomes", header: "Outcomes", align: "right" },
              {
                key: "net_impact_paise",
                header: "Net impact",
                align: "right",
                render: (row) => inrExact(row.net_impact_paise),
              },
              {
                key: "mean_absolute_error",
                header: "MAE",
                align: "right",
                render: (row) => (row.mean_absolute_error === null ? "—" : pct(row.mean_absolute_error)),
              },
            ]}
          />
        </Card>

        <Card title="Top customers by captured GMV" subtitle="Identifiers only — no personal data leaves the world model." stale={analytics.refreshing}>
          <DataTable
            rows={topCustomers}
            rowKey={(row) => row.customer_id}
            columns={[
              { key: "customer_id", header: "Customer", render: (row) => <span className="mono">{row.customer_id}</span> },
              { key: "payments", header: "Payments", align: "right" },
              { key: "gmv_paise", header: "GMV", align: "right", render: (row) => inrExact(row.gmv_paise) },
            ]}
          />
        </Card>
      </div>

      <Card title="Document counts for this merchant" subtitle="Every collection the world model writes.">
        <div className="grid g5">
          {Object.entries(totals).map(([name, count]) => (
            <div key={name} className="stack-v" style={{ gap: 2 }}>
              <span className="tiny mono">{name}</span>
              <strong className="num" style={{ fontSize: 16 }}>
                {num(Number(count))}
              </strong>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
