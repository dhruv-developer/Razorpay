"use client";

import { useMemo, useState } from "react";
import { PageHead } from "@/components/Shell";
import { BarList, ChartFrame } from "@/components/charts";
import { Badge, Card, DataTable, Drawer, Empty, ErrorNote, Json, KeyValues, StatCard, Tabs } from "@/components/ui";
import { ACTION_TYPES, brain } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { dateTime, inr, inrExact, num, pct, relativeTime, titleCase, toneFor } from "@/lib/format";

const STATUS_TONE: Record<string, "good" | "critical" | "serious" | "warning" | "neutral"> = {
  passed: "good",
  failed: "critical",
  errored: "critical",
  skipped: "warning",
};

export default function TestLabPage() {
  const last = useResource(() => brain.lastSelfTest(), []);
  const { busy, error: actionError, message, run } = useAction();
  const [report, setReport] = useState<any>(null);
  const [mutating, setMutating] = useState(false);
  const [tab, setTab] = useState("suite");
  const [open, setOpen] = useState<any>(null);

  // Manual action probe
  const [actionType, setActionType] = useState<string>("observe");
  const [amount, setAmount] = useState("0");
  const [reason, setReason] = useState("Manual probe from the admin test lab");
  const [probe, setProbe] = useState<any>(null);

  const checks: any[] = report?.checks || [];
  const summary = report?.summary;

  const byLayer = useMemo(() => {
    const counts = new Map<string, { passed: number; total: number }>();
    for (const check of checks) {
      const entry = counts.get(check.layer) || { passed: 0, total: 0 };
      entry.total += 1;
      if (check.status === "passed") entry.passed += 1;
      counts.set(check.layer, entry);
    }
    return [...counts.entries()].map(([key, value]) => ({
      key,
      label: titleCase(key),
      value: value.passed,
      total: value.total,
    }));
  }, [checks]);

  const slowest = [...checks].sort((a, b) => b.duration_ms - a.duration_ms).slice(0, 8);

  async function runSuite() {
    await run(
      "suite",
      async () => {
        const result = await brain.selfTest(mutating);
        setReport(result);
        await last.reload();
      },
      "Suite finished.",
    );
  }

  async function runProbe() {
    await run("probe", async () => {
      const created: any = await brain.createAction({
        type: actionType,
        amount: Math.round(Number(amount) || 0),
        reason,
        agent_id: "admin_console",
      });
      setProbe({ created });
    });
  }

  async function decideProbe(approve: boolean) {
    if (!probe?.created) return;
    await run(approve ? "approve" : "reject", async () => {
      const result = approve
        ? await brain.approve(probe.created.action_id, probe.created.approval_token)
        : await brain.reject(probe.created.action_id, probe.created.approval_token);
      const refreshed = await brain.action(probe.created.action_id);
      setProbe({ created: refreshed, result });
    });
  }

  return (
    <>
      <PageHead
        title="Test lab"
        description="Run the whole system end to end from here. Each check asserts a real invariant against live data and reports what it found."
        actions={
          <>
            <label className="checkbox">
              <input type="checkbox" checked={mutating} onChange={(e) => setMutating(e.target.checked)} />
              Include write checks
            </label>
            <button className="btn" disabled={!!busy} onClick={runSuite}>
              {busy === "suite" ? "Running suite…" : "Run self-test"}
            </button>
          </>
        }
      />
      <ErrorNote>{actionError}</ErrorNote>
      {message && <p className="notice">{message}</p>}
      {mutating && (
        <p className="notice">
          Write checks create and execute a real <span className="mono">observe</span> action, a rejected high-value
          refund request, an orchestration run and one de-duplicated event. They move no money, but they do add rows to
          the actions, approvals, outcomes, recommendations and audit collections.
        </p>
      )}

      {report ? (
        <div className="grid g5">
          <StatCard
            label="Result"
            value={summary.ok ? "All passing" : `${summary.failed + summary.errored} failing`}
            tone={summary.ok ? "good" : "critical"}
            foot={`${summary.passed}/${summary.total} checks`}
          />
          <StatCard label="Passed" value={num(summary.passed)} tone="good" />
          <StatCard label="Failed" value={num(summary.failed + summary.errored)} tone={summary.failed + summary.errored ? "critical" : undefined} />
          <StatCard label="Skipped" value={num(summary.skipped)} foot={mutating ? "none skipped" : "write checks off"} />
          <StatCard label="Duration" value={`${(report.duration_ms / 1000).toFixed(2)}s`} foot={dateTime(report.ran_at)} />
        </div>
      ) : (
        <Card>
          <Empty
            title="No suite run in this session"
            hint={
              last.data?.last_run
                ? `Last stored run: ${last.data.last_run.summary.passed}/${last.data.last_run.summary.total} passed, ${relativeTime(last.data.last_run.ran_at)}.`
                : "Press “Run self-test” to exercise every layer."
            }
          />
        </Card>
      )}

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "suite", label: "Checks", count: checks.length || undefined },
          { id: "coverage", label: "Coverage" },
          { id: "probe", label: "Action probe" },
        ]}
      />

      {tab === "suite" && (
        <Card
          title="Checks"
          subtitle="Green means the assertion held against your live data — not that a mock returned a canned value."
        >
          {checks.length ? (
            <DataTable
              rows={checks}
              rowKey={(row) => row.id}
              onRowClick={setOpen}
              columns={[
                {
                  key: "status",
                  header: "Result",
                  render: (row) => <Badge tone={STATUS_TONE[row.status] || "neutral"}>{titleCase(row.status)}</Badge>,
                },
                { key: "title", header: "Check", render: (row) => <strong style={{ fontWeight: 550 }}>{row.title}</strong> },
                { key: "layer", header: "Layer", render: (row) => <span className="tiny">{titleCase(row.layer)}</span> },
                {
                  key: "kind",
                  header: "Kind",
                  render: (row) => (
                    <Badge tone={row.kind === "mutate" ? "warning" : "neutral"} glyph={false}>
                      {row.kind}
                    </Badge>
                  ),
                },
                { key: "duration_ms", header: "Duration", align: "right", render: (row) => `${row.duration_ms} ms` },
                {
                  key: "detail",
                  header: "Detail",
                  render: (row) => (
                    <span className="cell-clip tiny" title={JSON.stringify(row.detail)}>
                      {row.detail?.assertion || row.detail?.error || JSON.stringify(row.detail)}
                    </span>
                  ),
                },
              ]}
            />
          ) : (
            <Empty title="Run the suite to populate this" />
          )}
        </Card>
      )}

      {tab === "coverage" && (
        <div className="grid split">
          <ChartFrame
            title="Checks passing by layer"
            subtitle="Every layer of the system is covered by at least one assertion."
            table={{
              columns: ["Layer", "Passed", "Total"],
              rows: byLayer.map((l) => [l.label, num(l.value), num(l.total)]),
            }}
          >
            {byLayer.length ? (
              <BarList
                items={byLayer}
                format={num}
                meta={(item) => {
                  const layer = byLayer.find((l) => l.key === item.key);
                  return <span className="tiny">of {layer?.total}</span>;
                }}
              />
            ) : (
              <Empty title="Run the suite first" />
            )}
          </ChartFrame>

          <ChartFrame
            title="Slowest checks"
            subtitle="Where the time actually goes."
            table={{
              columns: ["Check", "Duration (ms)"],
              rows: slowest.map((c) => [c.title, String(c.duration_ms)]),
            }}
          >
            {slowest.length ? (
              <BarList
                items={slowest.map((c) => ({ key: c.id, label: c.id, value: c.duration_ms }))}
                format={(v) => `${v} ms`}
              />
            ) : (
              <Empty title="Run the suite first" />
            )}
          </ChartFrame>
        </div>
      )}

      {tab === "probe" && (
        <div className="grid split">
          <Card
            title="Create an action by hand"
            subtitle="Exercises the policy gate, the approval flow and the executor exactly as an agent would."
          >
            <div className="grid g3">
              <label className="field">
                Action type
                <select value={actionType} onChange={(e) => setActionType(e.target.value)}>
                  {ACTION_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                Amount (paise)
                <input type="number" min={0} value={amount} onChange={(e) => setAmount(e.target.value)} />
                <span className="tiny">{inr(Number(amount))}</span>
              </label>
              <label className="field">
                Reason
                <input value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" disabled={!!busy} onClick={runProbe}>
                {busy === "probe" ? "Creating…" : "Create action"}
              </button>
              <span className="tiny">
                An <span className="mono">observe</span> action auto-authorises; a large{" "}
                <span className="mono">refund.create</span> should come back pending approval.
              </span>
            </div>

            {probe?.created && (
              <div style={{ marginTop: 16 }}>
                <KeyValues
                  rows={[
                    ["Action id", <span className="mono">{probe.created.action_id}</span>],
                    ["Status", <Badge tone={toneFor(probe.created.status)}>{titleCase(probe.created.status)}</Badge>],
                    ["Requires approval", probe.created.requires_approval ? "yes" : "no"],
                    ["Policy reasons", (probe.created.policy_result?.reasons || []).join(" ") || "none"],
                    ["Action level", probe.created.policy_result?.action_level],
                    ["Reversibility", titleCase(probe.created.reversibility)],
                    ["Amount", inrExact(probe.created.amount_paise)],
                  ]}
                />
                <div className="row" style={{ marginTop: 12 }}>
                  <button className="btn sm" disabled={!!busy} onClick={() => decideProbe(true)}>
                    {busy === "approve" ? "Approving…" : "Approve & execute"}
                  </button>
                  <button className="btn subtle sm" disabled={!!busy} onClick={() => decideProbe(false)}>
                    {busy === "reject" ? "Rejecting…" : "Reject"}
                  </button>
                </div>
              </div>
            )}
          </Card>

          <Card title="Probe result" subtitle="The complete record the executor wrote back.">
            {probe ? (
              <>
                {probe.result && (
                  <div style={{ marginBottom: 12 }}>
                    <div className="card-title" style={{ marginBottom: 6 }}>
                      Decision result
                    </div>
                    <Json value={probe.result} maxHeight={220} />
                  </div>
                )}
                <div className="card-title" style={{ marginBottom: 6 }}>
                  Action document
                </div>
                <Json value={probe.created} maxHeight={320} />
              </>
            ) : (
              <Empty title="No probe run yet" hint="Create an action on the left to see the whole safety pipeline respond." />
            )}
          </Card>
        </div>
      )}

      <Drawer
        open={!!open}
        title={open?.title || ""}
        subtitle={open ? `${open.id} · ${open.layer} · ${open.duration_ms} ms` : undefined}
        onClose={() => setOpen(null)}
      >
        {open && (
          <>
            <KeyValues
              rows={[
                ["Result", <Badge tone={STATUS_TONE[open.status] || "neutral"}>{titleCase(open.status)}</Badge>],
                ["Kind", open.kind],
                ["Layer", titleCase(open.layer)],
                ["Duration", `${open.duration_ms} ms`],
              ]}
            />
            <div>
              <div className="card-title" style={{ marginBottom: 6 }}>
                What the check found
              </div>
              <Json value={open.detail} />
            </div>
          </>
        )}
      </Drawer>
    </>
  );
}
