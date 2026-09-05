"use client";

import { useState } from "react";
import { PageHead } from "@/components/Shell";
import { BarList, ChartFrame, SERIES } from "@/components/charts";
import { Badge, Card, DataTable, Drawer, Empty, ErrorNote, Json, KeyValues, StatCard, StatusBadge } from "@/components/ui";
import { brain } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { dateTime, inr, inrExact, num, pct, relativeTime, titleCase, toneFor } from "@/lib/format";

/** Ordered lifecycle stages, so the funnel can use the ordinal ramp. */
const STAGES = ["PENDING_APPROVAL", "AUTHORIZED", "APPROVED", "REJECTED", "VERIFIED", "FAILED"];

export default function PipelinePage() {
  const pipeline = useResource(() => brain.pipeline(), []);
  const approvals = useResource(() => brain.approvals(), []);
  const { busy, error: actionError, message, run } = useAction();
  const [open, setOpen] = useState<any>(null);
  const [openRec, setOpenRec] = useState<any>(null);

  const recommendations: any[] = pipeline.data?.recommendations || [];
  const actions: any[] = pipeline.data?.actions || [];
  const approvalRows: any[] = approvals.data?.approvals || [];

  const counts = STAGES.map((stage) => ({
    key: stage,
    label: titleCase(stage),
    value: actions.filter((a) => a.status === stage).length,
  })).filter((s) => s.value > 0);

  const withOutcome = actions.filter((a) => a.outcome);
  const errors = withOutcome
    .map((a) => a.outcome.prediction_error)
    .filter((e: any) => e !== null && e !== undefined) as number[];
  const mae = errors.length ? errors.reduce((s, e) => s + e, 0) / errors.length : null;
  // Only actions that actually predicted something belong in a calibration
  // chart; a read-only `observe` has nothing to be right or wrong about.
  const calibrated = withOutcome.filter(
    (a) => Number(a.outcome.expected_impact_paise) || Number(a.outcome.actual_impact_paise),
  );

  const reload = () => Promise.all([pipeline.reload(), approvals.reload()]);

  return (
    <>
      <PageHead
        title="Decision pipeline"
        description="Recommendation → policy gate → approval → execution → verification → outcome. Every hop is a stored document, and every one is visible here."
        actions={
          <button className="btn ghost sm" onClick={reload} disabled={pipeline.refreshing}>
            {pipeline.refreshing ? "Refreshing…" : "Refresh"}
          </button>
        }
      />
      <ErrorNote>{pipeline.error || approvals.error || actionError}</ErrorNote>
      {message && <p className="notice">{message}</p>}

      <div className="grid g5">
        <StatCard label="Recommendations" value={num(recommendations.length)} />
        <StatCard label="Actions created" value={num(actions.length)} />
        <StatCard
          label="Approvals issued"
          value={num(approvalRows.length)}
          foot={`${approvalRows.filter((a) => a.status === "PENDING").length} still pending`}
        />
        <StatCard label="Outcomes measured" value={num(withOutcome.length)} tone="good" />
        <StatCard
          label="Mean prediction error"
          value={mae === null ? "—" : pct(mae)}
          foot="Across every verified action"
          tone={mae !== null && mae > 0.5 ? "warning" : undefined}
        />
      </div>

      <div className="grid split">
        <ChartFrame
          title="Action lifecycle"
          subtitle="Where actions currently sit. Ordered stages use the ordinal ramp."
          stale={pipeline.refreshing}
          table={{ columns: ["Stage", "Actions"], rows: counts.map((c) => [c.label, num(c.value)]) }}
        >
          {counts.length ? <BarList items={counts} format={num} ordinal /> : <Empty title="No actions yet" />}
        </ChartFrame>

        <ChartFrame
          title="Expected against measured impact"
          subtitle="Actions that made a prediction, in the order they executed."
          stale={pipeline.refreshing}
          legend={[
            { key: "expected", label: "Expected" },
            { key: "actual", label: "Measured" },
          ]}
          table={{
            columns: ["Action", "Expected", "Measured", "Error"],
            rows: calibrated.map((a) => [
              a.action_type,
              inrExact(a.outcome.expected_impact_paise),
              inrExact(a.outcome.actual_impact_paise),
              a.outcome.prediction_error === null ? "—" : pct(a.outcome.prediction_error),
            ]),
          }}
        >
          {calibrated.length ? (
            <div className="stack-v">
              {calibrated.slice(0, 8).map((a) => (
                <div key={a.action_id} className="stack-v" style={{ gap: 5 }}>
                  <div className="spread" style={{ fontSize: 12.5 }}>
                    <span className="mono">{a.action_type}</span>
                    <span className="tiny">
                      {a.outcome.prediction_error === null ? "no baseline" : `${pct(a.outcome.prediction_error)} error`}
                    </span>
                  </div>
                  <TwoBar
                    expected={a.outcome.expected_impact_paise}
                    actual={a.outcome.actual_impact_paise}
                    max={Math.max(
                      ...calibrated.flatMap((x) => [
                        Math.abs(x.outcome.expected_impact_paise),
                        Math.abs(x.outcome.actual_impact_paise),
                      ]),
                      1,
                    )}
                  />
                </div>
              ))}
            </div>
          ) : (
            <Empty
              title="No predicted outcomes yet"
              hint="Approve an action that moves money — read-only probes have nothing to calibrate against."
            />
          )}
        </ChartFrame>
      </div>

      <Card
        title="Recommendations and the actions they produced"
        subtitle="Click a recommendation for the whole record, including the alternatives it rejected."
      >
        {recommendations.length ? (
          <div className="stack-v" style={{ gap: 12 }}>
            {recommendations.slice(0, 10).map((rec) => (
              <div key={rec.recommendation_id} style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
                <div className="spread" style={{ alignItems: "flex-start" }}>
                  <div>
                    <div className="row tight">
                      <StatusBadge value={rec.status} />
                      <Badge tone={toneFor(rec.risk)}>{titleCase(rec.risk)} risk</Badge>
                      <strong style={{ fontSize: 13 }}>{rec.problem}</strong>
                    </div>
                    <p className="tiny" style={{ marginTop: 4 }}>
                      {rec.why_this} · confidence {pct(rec.confidence)} · {relativeTime(rec.created_at)}
                    </p>
                  </div>
                  <button className="btn ghost xs" onClick={() => setOpenRec(rec)}>
                    Record
                  </button>
                </div>
                {(rec.actions || []).length ? (
                  <div className="rowlist" style={{ marginTop: 8 }}>
                    {(rec.actions || []).map((action: any) => (
                      <div key={action.action_id}>
                        <span className="row tight">
                          <span className="mono">{action.action_type}</span>
                          <StatusBadge value={action.status} />
                          {action.approval && <Badge tone={toneFor(action.approval.status)}>approval {titleCase(action.approval.status)}</Badge>}
                        </span>
                        <span className="row tight">
                          <span className="tiny num">{inr(action.amount_paise)}</span>
                          {action.outcome && (
                            <span className="tiny num">→ measured {inr(action.outcome.actual_impact_paise)}</span>
                          )}
                          <button className="btn xs subtle" onClick={() => setOpen(action)}>
                            Trace
                          </button>
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="tiny" style={{ marginTop: 8 }}>
                    No action was created from this recommendation.
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <Empty title="No recommendations yet" hint="Run an orchestration from Decisions or Agents." />
        )}
      </Card>

      <Card title="Approval tokens" subtitle="One single-use token per gated action, with its own expiry.">
        <DataTable
          rows={approvalRows}
          rowKey={(row) => row.token}
          columns={[
            { key: "action_type", header: "Action", render: (row) => <span className="mono">{row.action_type}</span> },
            { key: "status", header: "Status", render: (row) => <StatusBadge value={row.status} /> },
            { key: "amount_paise", header: "Amount", align: "right", render: (row) => inrExact(row.amount_paise) },
            { key: "action_id", header: "Action id", render: (row) => <span className="mono">{row.action_id}</span> },
            { key: "created_at", header: "Issued", render: (row) => dateTime(row.created_at) },
            {
              key: "expires_at",
              header: "Expires",
              render: (row) => (
                <span className="row tight">
                  {dateTime(row.expires_at)}
                  {row.expired && row.status === "PENDING" && <Badge tone="critical">expired</Badge>}
                </span>
              ),
            },
            {
              key: "decide",
              header: "",
              align: "right",
              render: (row) =>
                row.status === "PENDING" ? (
                  <span className="row tight" style={{ justifyContent: "flex-end" }}>
                    <button
                      className="btn xs"
                      disabled={!!busy}
                      onClick={() =>
                        run(`ok-${row.token}`, async () => {
                          await brain.approve(row.action_id, row.token);
                          await reload();
                        }, "Approved and executed.")
                      }
                    >
                      Approve
                    </button>
                    <button
                      className="btn subtle xs"
                      disabled={!!busy}
                      onClick={() =>
                        run(`no-${row.token}`, async () => {
                          await brain.reject(row.action_id, row.token);
                          await reload();
                        }, "Rejected.")
                      }
                    >
                      Reject
                    </button>
                  </span>
                ) : (
                  <span className="tiny">{row.resolved_at ? dateTime(row.resolved_at) : "—"}</span>
                ),
            },
          ]}
          empty="No approval has ever been required."
        />
      </Card>

      <Drawer
        open={!!open}
        title={open?.action_type || ""}
        subtitle={open ? `${open.action_id} · trace ${open.trace_id}` : undefined}
        onClose={() => setOpen(null)}
      >
        {open && (
          <>
            <KeyValues
              rows={[
                ["Status", <StatusBadge value={open.status} />],
                ["Policy gate", open.requires_approval ? "approval required" : "auto-authorised"],
                ["Reasons", (open.policy_result?.reasons || []).join(" ") || "—"],
                ["Action level", open.policy_result?.action_level],
                ["Reversibility", titleCase(open.reversibility)],
                ["Created", dateTime(open.created_at)],
                ["Executed", open.executed_at ? dateTime(open.executed_at) : "—"],
                ["Verified", open.verification?.detail || "—"],
                [
                  "Outcome",
                  open.outcome
                    ? `${inrExact(open.outcome.actual_impact_paise)} measured vs ${inrExact(open.outcome.expected_impact_paise)} expected`
                    : "—",
                ],
              ]}
            />
            <Json value={open} maxHeight={100000} />
          </>
        )}
      </Drawer>

      <Drawer open={!!openRec} title={openRec?.problem || ""} subtitle={openRec?.recommendation_id} onClose={() => setOpenRec(null)}>
        {openRec && <Json value={openRec} maxHeight={100000} />}
      </Drawer>
    </>
  );
}

function TwoBar({ expected, actual, max }: { expected: number; actual: number; max: number }) {
  return (
    <div className="stack-v" style={{ gap: 2 }}>
      {[
        { label: "Expected", value: expected, color: SERIES[0] },
        { label: "Measured", value: actual, color: SERIES[2] },
      ].map((bar) => (
        <div key={bar.label} className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
          <span className="tiny" style={{ width: 62, flex: "none" }}>
            {bar.label}
          </span>
          <div style={{ flex: 1, height: 8, background: "var(--surface-3)", borderRadius: 4, overflow: "hidden" }}>
            <div
              style={{
                width: `${(Math.abs(bar.value) / max) * 100}%`,
                height: "100%",
                background: bar.color,
                borderRadius: 4,
              }}
            />
          </div>
          <span className="tiny num" style={{ width: 84, textAlign: "right", flex: "none" }}>
            {inr(bar.value)}
          </span>
        </div>
      ))}
    </div>
  );
}
