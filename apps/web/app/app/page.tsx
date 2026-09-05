"use client";

import Link from "next/link";
import { PageHead } from "@/components/Shell";
import { BandChart, BarList, ChartFrame, LineChart, SERIES, Sparkline } from "@/components/charts";
import { Badge, Card, ErrorNote, Empty, Meter, Skeleton, StatCard, StatusBadge } from "@/components/ui";
import { brain } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { dateTime, inr, inrExact, num, pct, relativeTime, timeOfDay, titleCase, toneFor } from "@/lib/format";

const VECTOR: [string, string, string][] = [
  ["liquidity", "Liquidity", "Cash against the configured reserve band"],
  ["transaction_health", "Transaction health", "24h failure rate against the 7d baseline"],
  ["settlement_health", "Settlement health", "Share of settlements that are not delayed"],
  ["customer_health", "Customer health", "Returning share of the customer base"],
  ["receivables", "Receivables", "Collected share of open invoices"],
  ["payables", "Payables", "Cash cover for scheduled payouts"],
  ["confidence", "Confidence", "How much data backs this state vector"],
];

export default function OverviewPage() {
  const health = useResource(() => brain.health(), []);
  const history = useResource(() => brain.stateHistory(40), []);
  const attention = useResource(() => brain.attention(), []);
  const why = useResource(() => brain.why(), []);
  const { busy, error: actionError, run } = useAction();

  const state = health.data?.state || {};
  const forecast = health.data?.forecast || {};
  const weather = health.data?.weather || forecast.weather || [];
  const points: any[] = history.data?.points || [];
  const items: any[] = attention.data?.items || [];
  const drivers: any[] = why.data?.primary_drivers || [];

  const cashSeries = points.map((p) => p.cash_paise);
  const revenueSeries = points.map((p) => p.revenue_24h_paise);
  const riskSeries = points.map((p) => p.operational_risk);
  const failSeries = points.map((p) => p.failure_rate_24h);

  const label = state.label || "unknown";
  const refreshing = health.refreshing || history.refreshing;

  async function runCycle() {
    await run("cycle", async () => {
      await brain.cycle();
      await Promise.all([health.reload(), history.reload(), attention.reload(), why.reload()]);
    });
  }

  return (
    <>
      <PageHead
        title="Business health"
        description={
          <>
            Live world state for this merchant.{" "}
            {state.computed_at ? <>Recomputed {relativeTime(state.computed_at)}.</> : null}
          </>
        }
        actions={
          <>
            <StatusBadge value={label} />
            <button className="btn" disabled={busy === "cycle"} onClick={runCycle}>
              {busy === "cycle" ? "Running brain cycle…" : "Run brain cycle"}
            </button>
          </>
        }
      />

      <ErrorNote>{health.error || actionError}</ErrorNote>

      {health.loading ? (
        <div className="grid g4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} height={120} />
          ))}
        </div>
      ) : (
        <div className="grid g4">
          <StatCard
            label="Revenue 24h"
            value={inr(state.revenue_24h_paise)}
            delta={{ value: Number(state.revenue_delta || 0), label: "vs 7d daily baseline" }}
            chart={<Sparkline values={revenueSeries} color={SERIES[0]} />}
          />
          <StatCard
            label="Cash on hand"
            value={inr(state.cash_paise)}
            foot={
              <>
                Projected 24h <strong>{inr(state.projected_cash_24h_paise)}</strong> · reserve{" "}
                {inr(state.cash_reserve_minimum_paise)}
              </>
            }
            chart={<Sparkline values={cashSeries} color={SERIES[2]} />}
          />
          <StatCard
            label="Reserve breach risk"
            value={pct(state.reserve_breach_probability)}
            tone={toneFor(
              Number(state.reserve_breach_probability) >= 0.5
                ? "critical"
                : Number(state.reserve_breach_probability) >= 0.25
                  ? "high"
                  : "low",
            )}
            foot={<>Operational risk {pct(state.operational_risk)}</>}
            chart={<Sparkline values={riskSeries} color={SERIES[3]} />}
          />
          <StatCard
            label="Payment success 24h"
            value={pct(state.success_rate_24h)}
            delta={{
              value: Number(state.failure_rate_7d)
                ? Number(state.failure_rate_24h) / Number(state.failure_rate_7d) - 1
                : 0,
              label: "failure vs 7d",
              goodWhenUp: false,
            }}
            chart={<Sparkline values={failSeries} color={SERIES[1]} />}
          />
        </div>
      )}

      <div className="grid split">
        <ChartFrame
          title="Cash forecast"
          subtitle="p50 line with the p10–p90 band from the trend-residual model."
          stale={refreshing}
          table={{
            columns: ["Horizon", "p10", "p50", "p90"],
            rows: (forecast.horizons || []).map((h: any) => [
              h.horizon,
              inrExact(h.cash.p10),
              inrExact(h.cash.p50),
              inrExact(h.cash.p90),
            ]),
          }}
        >
          <BandChart
            points={(forecast.horizons || []).map((h: any) => ({
              label: h.horizon,
              p10: h.cash.p10,
              p50: h.cash.p50,
              p90: h.cash.p90,
            }))}
            format={inr}
          />
        </ChartFrame>

        <Card
          title="Financial weather"
          subtitle="Cash against the reserve band over the next three days."
          stale={refreshing}
        >
          {weather.length ? (
            <div className="stack-v">
              {weather.map((day: any) => (
                <div key={day.label} className="stack-v" style={{ gap: 5 }}>
                  <div className="spread" style={{ fontSize: 12.5 }}>
                    <span>{day.label}</span>
                    <span className="row tight">
                      <strong className="num">{inr(day.cash_paise)}</strong>
                      <Badge tone={toneFor(day.risk)}>{day.status}</Badge>
                    </span>
                  </div>
                  <Meter
                    value={day.score}
                    tone={day.risk === "low" ? "good" : day.risk === "medium" ? "warning" : day.risk === "high" ? "serious" : "critical"}
                  />
                </div>
              ))}
              <p className="tiny">
                Model {forecast.model_version} · confidence {pct(forecast.confidence)} · data quality{" "}
                {pct(forecast.data_quality)}
              </p>
            </div>
          ) : (
            <Empty title="No forecast yet" hint="Run a brain cycle to generate one." />
          )}
        </Card>
      </div>

      <div className="grid split">
        <ChartFrame
          title="Cash and projected cash"
          subtitle="Every recomputed world state, oldest to newest."
          stale={refreshing}
          legend={[
            { key: "cash_paise", label: "Cash" },
            { key: "projected_cash_24h_paise", label: "Projected 24h" },
            { key: "cash_reserve_minimum_paise", label: "Reserve floor" },
          ]}
          table={{
            columns: ["Computed", "Cash", "Projected 24h", "Reserve"],
            rows: points
              .slice(-20)
              .reverse()
              .map((p) => [dateTime(p.computed_at), inrExact(p.cash_paise), inrExact(p.projected_cash_24h_paise), inrExact(p.cash_reserve_minimum_paise)]),
          }}
        >
          <LineChart
            points={points}
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

        <Card title="State vector" subtitle="Every dimension the agents read before proposing." stale={refreshing}>
          <div className="stack-v">
            {VECTOR.map(([key, label, hint]) => (
              <div key={key} className="stack-v" style={{ gap: 4 }}>
                <div className="spread" style={{ fontSize: 12.5 }}>
                  <span title={hint}>{label}</span>
                  <strong className="num">{pct(state[key])}</strong>
                </div>
                <Meter value={Number(state[key] || 0)} />
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="grid split">
        <Card
          title="Needs attention"
          subtitle="Ranked by impact × urgency × confidence × reversibility."
          actions={
            <Link className="btn ghost sm" href="/app/attention">
              Open queue
            </Link>
          }
          stale={attention.refreshing}
        >
          {items.length ? (
            <div className="stack-v">
              {items.slice(0, 4).map((item) => (
                <div key={item.id} className="spread" style={{ gap: 12, alignItems: "flex-start" }}>
                  <div>
                    <div className="row tight">
                      <Badge tone={toneFor(item.severity)}>{titleCase(item.severity)}</Badge>
                      <strong style={{ fontSize: 13 }}>{item.title}</strong>
                    </div>
                    <p className="tiny" style={{ marginTop: 3 }}>
                      {item.why}
                    </p>
                  </div>
                  <strong className="num" style={{ whiteSpace: "nowrap" }}>
                    {inr(item.impact_paise)}
                  </strong>
                </div>
              ))}
            </div>
          ) : (
            <Empty title="Nothing needs you right now" hint="No item cleared the attention threshold." />
          )}
        </Card>

        <ChartFrame
          title="What is moving cash"
          subtitle={why.data?.cash_story}
          stale={why.refreshing}
          table={{
            columns: ["Driver", "Impact", "Confidence"],
            rows: drivers.map((d) => [d.claim, inrExact(d.impact_paise), pct(d.confidence)]),
          }}
        >
          <BarList
            items={drivers.map((d, i) => ({ key: `${i}`, label: d.claim, value: d.impact_paise }))}
            format={inr}
            meta={(_, index) => <span className="tiny">{pct(drivers[index]?.confidence)} conf</span>}
          />
        </ChartFrame>
      </div>

      <Card title="Balance sheet of unresolved money" subtitle="The same figures the recovery agents act on.">
        <div className="grid g4">
          {[
            ["Pending settlements", state.pending_settlement_paise],
            ["Delayed settlements", state.delayed_settlement_paise],
            ["Overdue receivables", state.overdue_receivables_paise],
            ["Scheduled payouts", state.scheduled_payouts_paise],
            ["Open disputes", state.open_disputes_paise],
            ["Pending refunds", state.pending_refunds_paise],
            ["Failed payments 48h", state.failed_recovery_paise],
            ["Scheduled payroll", state.payroll_scheduled_paise],
          ].map(([label, value]) => (
            <div key={String(label)} className="stack-v" style={{ gap: 2 }}>
              <span className="tiny">{label}</span>
              <strong className="num" style={{ fontSize: 16 }}>
                {inr(Number(value || 0))}
              </strong>
            </div>
          ))}
        </div>
        <p className="tiny" style={{ marginTop: 12 }}>
          Average order value {inr(state.average_order_value_paise)} · {num(points.length)} state snapshots retained ·
          currency {state.currency || "INR"}
        </p>
      </Card>
    </>
  );
}
