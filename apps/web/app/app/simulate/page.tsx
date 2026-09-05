"use client";

import { useMemo, useState } from "react";
import { PageHead } from "@/components/Shell";
import { BarList, ChartFrame, SERIES } from "@/components/charts";
import { Badge, Card, DataTable, Drawer, Empty, ErrorNote, Json, KeyValues, Segmented, StatCard, StatusBadge } from "@/components/ui";
import { ACTION_TYPES, brain } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { inr, inrExact, pct, titleCase, toneFor } from "@/lib/format";

type DraftAction = { type: string; amount: number; duration_hours?: number };

export default function SimulatePage() {
  const state = useResource(() => brain.state(), []);
  const { busy, error: actionError, run } = useAction();
  const [rows, setRows] = useState<any[]>([]);
  const [horizon, setHorizon] = useState(48);
  const [draft, setDraft] = useState<DraftAction[]>([{ type: "payout.delay", amount: 0, duration_hours: 12 }]);
  const [single, setSingle] = useState<any>(null);
  const [open, setOpen] = useState<any>(null);

  const s = state.data || {};
  const payouts = Number(s.scheduled_payouts_paise || 0);
  const overdue = Number(s.overdue_receivables_paise || 0);
  const failed = Number(s.failed_recovery_paise || 0);
  const pending = Number(s.pending_settlement_paise || 0);

  const presets = useMemo(
    () => [
      { label: "Do nothing", actions: [{ type: "observe", amount: 0 }] },
      { label: "Delay payouts 12h", actions: [{ type: "payout.delay", amount: payouts, duration_hours: 12 }] },
      { label: "Recover receivables", actions: [{ type: "receivable.recover", amount: overdue }] },
      { label: "Retry failed payments", actions: [{ type: "payment.retry", amount: failed }] },
      {
        label: "Delay + recover",
        actions: [
          { type: "payout.delay", amount: payouts, duration_hours: 12 },
          { type: "receivable.recover", amount: overdue },
        ],
      },
      {
        label: "Everything at once",
        actions: [
          { type: "payout.delay", amount: payouts, duration_hours: 24 },
          { type: "receivable.recover", amount: overdue },
          { type: "payment.retry", amount: failed },
        ],
      },
    ],
    [payouts, overdue, failed],
  );

  const baseline = rows.find((r) => r.label === "Do nothing");

  async function compare() {
    await run("compare", async () => {
      const res: any = await brain.compare(presets, horizon);
      setRows(res.options || []);
    });
  }

  async function runDraft() {
    await run("single", async () => {
      const cleaned = draft
        .filter((a) => a.type)
        .map((a) => ({
          type: a.type,
          amount: Math.round(Number(a.amount) || 0),
          ...(a.duration_hours ? { duration_hours: Number(a.duration_hours) } : {}),
        }));
      setSingle(await brain.simulate(cleaned, horizon));
    });
  }

  return (
    <>
      <PageHead
        title="What if?"
        description="Counterfactuals against the live world state. Simulations never touch money — they are the same engine the orchestrator scores options with."
        actions={
          <>
            <Segmented
              label="Horizon"
              value={horizon}
              onChange={setHorizon}
              options={[
                { value: 24, label: "24h" },
                { value: 48, label: "48h" },
                { value: 72, label: "72h" },
              ]}
            />
            <button className="btn" disabled={!!busy} onClick={compare}>
              {busy === "compare" ? "Simulating…" : "Compare options"}
            </button>
          </>
        }
      />
      <ErrorNote>{state.error || actionError}</ErrorNote>

      <div className="grid g5">
        <StatCard label="Cash now" value={inr(s.cash_paise)} />
        <StatCard label="Projected 24h" value={inr(s.projected_cash_24h_paise)} foot={`Reserve ${inr(s.cash_reserve_minimum_paise)}`} />
        <StatCard label="Scheduled payouts" value={inr(payouts)} foot="Delayable" />
        <StatCard label="Overdue receivables" value={inr(overdue)} foot="Recoverable" />
        <StatCard label="Failed in 48h" value={inr(failed)} foot="Retryable" />
      </div>

      {rows.length ? (
        <>
          <div className="grid split">
            <ChartFrame
              title="Projected cash by option"
              subtitle={`Horizon ${horizon}h. All options simulated from the same starting state.`}
              table={{
                columns: ["Option", "Projected cash", "Breach probability", "Business impact", "Risk"],
                rows: rows.map((r) => [
                  titleCase(r.label),
                  inrExact(r.projected_cash_paise),
                  pct(r.reserve_breach_probability),
                  inrExact(r.expected_business_impact_paise),
                  titleCase(r.risk),
                ]),
              }}
            >
              <BarList
                items={rows.map((r) => ({ key: r.simulation_id, label: titleCase(r.label), value: r.projected_cash_paise }))}
                format={inr}
                meta={(item) => {
                  const row = rows.find((r) => r.simulation_id === item.key);
                  const delta = baseline ? row.projected_cash_paise - baseline.projected_cash_paise : 0;
                  return (
                    <span className="tiny">
                      {delta ? `${delta > 0 ? "+" : ""}${inr(delta)} vs do nothing` : "baseline"}
                    </span>
                  );
                }}
                maxRows={10}
              />
            </ChartFrame>

            <ChartFrame
              title="Reserve breach probability"
              subtitle="Lower is better. This is the constraint the orchestrator optimises against."
              table={{
                columns: ["Option", "Breach probability"],
                rows: rows.map((r) => [titleCase(r.label), pct(r.reserve_breach_probability)]),
              }}
            >
              <BarList
                items={rows.map((r) => ({ key: r.simulation_id, label: titleCase(r.label), value: r.reserve_breach_probability }))}
                format={(v) => pct(v)}
                color={SERIES[1]}
                maxRows={10}
              />
            </ChartFrame>
          </div>

          <Card title="Full comparison" subtitle="Click a row for the raw simulation record.">
            <DataTable
              rows={rows}
              rowKey={(row) => row.simulation_id}
              onRowClick={setOpen}
              columns={[
                { key: "label", header: "Option", render: (row) => <strong>{titleCase(row.label)}</strong> },
                { key: "projected_cash_paise", header: "Projected cash", align: "right", render: (row) => inrExact(row.projected_cash_paise) },
                {
                  key: "delta",
                  header: "vs do nothing",
                  align: "right",
                  render: (row) => {
                    if (!baseline) return "—";
                    const delta = row.projected_cash_paise - baseline.projected_cash_paise;
                    return (
                      <span style={{ color: delta > 0 ? "var(--good)" : delta < 0 ? "var(--critical)" : "var(--muted)" }}>
                        {delta > 0 ? "+" : ""}
                        {inrExact(delta)}
                      </span>
                    );
                  },
                },
                { key: "reserve_breach_probability", header: "Breach", align: "right", render: (row) => pct(row.reserve_breach_probability) },
                { key: "expected_business_impact_paise", header: "Impact", align: "right", render: (row) => inrExact(row.expected_business_impact_paise) },
                { key: "confidence", header: "Confidence", align: "right", render: (row) => pct(row.confidence) },
                { key: "risk", header: "Risk", render: (row) => <Badge tone={toneFor(row.risk)}>{titleCase(row.risk)}</Badge> },
              ]}
            />
          </Card>
        </>
      ) : (
        <Card>
          <Empty title="No comparison run yet" hint="Press “Compare options” to simulate six scenarios against the current state." />
        </Card>
      )}

      <div className="grid split">
        <Card
          title="Custom scenario"
          subtitle="Build any action list and simulate it. Nothing here executes — it only scores."
          actions={
            <button className="btn ghost sm" onClick={() => setDraft([...draft, { type: "observe", amount: 0 }])}>
              Add action
            </button>
          }
        >
          <div className="stack-v">
            {draft.map((action, index) => (
              <div key={index} className="row" style={{ gap: 8, alignItems: "flex-end" }}>
                <label className="field" style={{ flex: 2, minWidth: 150 }}>
                  Action
                  <select
                    value={action.type}
                    onChange={(e) => {
                      const next = [...draft];
                      next[index] = { ...action, type: e.target.value };
                      setDraft(next);
                    }}
                  >
                    {ACTION_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field" style={{ flex: 2, minWidth: 130 }}>
                  Amount (paise)
                  <input
                    type="number"
                    min={0}
                    value={action.amount}
                    onChange={(e) => {
                      const next = [...draft];
                      next[index] = { ...action, amount: Number(e.target.value) };
                      setDraft(next);
                    }}
                  />
                </label>
                <label className="field" style={{ flex: 1, minWidth: 90 }}>
                  Delay (h)
                  <input
                    type="number"
                    min={0}
                    value={action.duration_hours ?? ""}
                    onChange={(e) => {
                      const next = [...draft];
                      next[index] = { ...action, duration_hours: e.target.value ? Number(e.target.value) : undefined };
                      setDraft(next);
                    }}
                  />
                </label>
                <button
                  className="iconbtn"
                  aria-label="Remove action"
                  onClick={() => setDraft(draft.filter((_, i) => i !== index))}
                >
                  ✕
                </button>
              </div>
            ))}
            <div className="row">
              <button className="btn" disabled={!!busy} onClick={runDraft}>
                {busy === "single" ? "Simulating…" : "Simulate scenario"}
              </button>
              <span className="tiny">
                Shortcuts:{" "}
                {[
                  ["payouts", payouts],
                  ["overdue", overdue],
                  ["failed", failed],
                  ["pending settlements", pending],
                ].map(([label, value]) => (
                  <button
                    key={String(label)}
                    className="btn xs subtle"
                    style={{ marginRight: 4 }}
                    onClick={() => {
                      const next = [...draft];
                      next[next.length - 1] = { ...next[next.length - 1], amount: Number(value) };
                      setDraft(next);
                    }}
                  >
                    {label} {inr(Number(value))}
                  </button>
                ))}
              </span>
            </div>
          </div>
        </Card>

        <Card title="Scenario result" subtitle="The exact record the orchestrator would score.">
          {single ? (
            <>
              <KeyValues
                rows={[
                  ["Simulation", <span className="mono">{single.simulation_id}</span>],
                  ["Baseline cash", inrExact(single.baseline_projected_cash_paise)],
                  ["Projected cash", <strong>{inrExact(single.projected_cash_paise)}</strong>],
                  [
                    "Change",
                    <span
                      style={{
                        color:
                          single.projected_cash_paise > single.baseline_projected_cash_paise
                            ? "var(--good)"
                            : single.projected_cash_paise < single.baseline_projected_cash_paise
                              ? "var(--critical)"
                              : "var(--muted)",
                      }}
                    >
                      {inrExact(single.projected_cash_paise - single.baseline_projected_cash_paise)}
                    </span>,
                  ],
                  ["Breach probability", `${pct(single.baseline_reserve_breach_probability)} → ${pct(single.reserve_breach_probability)}`],
                  ["Business impact", inrExact(single.expected_business_impact_paise)],
                  ["Risk", <Badge tone={toneFor(single.risk)}>{titleCase(single.risk)}</Badge>],
                  ["Confidence", pct(single.confidence)],
                  ["Horizon", `${single.horizon_hours}h`],
                ]}
              />
              <div style={{ marginTop: 12 }}>
                <Json value={single} maxHeight={260} />
              </div>
            </>
          ) : (
            <Empty title="No scenario simulated yet" hint="Build an action list on the left and press Simulate." />
          )}
        </Card>
      </div>

      <Drawer open={!!open} title={titleCase(open?.label)} subtitle={open?.simulation_id} onClose={() => setOpen(null)}>
        {open && <Json value={open} maxHeight={100000} />}
      </Drawer>
    </>
  );
}
