"use client";

import { useEffect, useState } from "react";
import { PageHead } from "@/components/Shell";
import { Badge, Card, DataTable, ErrorNote, Json, StatCard } from "@/components/ui";
import { brain } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { inr, relativeTime, titleCase, toneFor } from "@/lib/format";

const AUTONOMY = [
  { value: "observe", label: "Observe", detail: "Watch only. Nothing may execute, not even a draft." },
  { value: "recommend", label: "Recommend", detail: "Propose and draft; every reversible action still needs you." },
  { value: "bounded", label: "Bounded", detail: "Reversible actions run unattended; financial ones still need approval." },
  { value: "autonomous", label: "Autonomous", detail: "Financial actions may run inside the configured limits." },
];

const MEMORY_KINDS = ["factual", "behavioral", "preference", "historical", "policy"];

const LEVELS: [string, number, string][] = [
  ["observe", 0, "Read-only"],
  ["invoice.dunning.draft", 1, "Draft"],
  ["receivable.recover", 1, "Draft"],
  ["retry.config.update", 2, "Reversible"],
  ["payment.retry", 2, "Reversible"],
  ["payout.delay", 2, "Reversible"],
  ["refund.create", 3, "Financial"],
  ["payout.create", 3, "Financial"],
];

export default function PolicyPage() {
  const policy = useResource(() => brain.policy(), []);
  const memories = useResource(() => brain.memories(), []);
  const { busy, error: actionError, message, run } = useAction();

  const [reserve, setReserve] = useState("");
  const [refundMax, setRefundMax] = useState("");
  const [payoutLimit, setPayoutLimit] = useState("");
  const [autonomy, setAutonomy] = useState("recommend");
  const [growth, setGrowth] = useState(0.3);
  const [cash, setCash] = useState(0.5);
  const [risk, setRisk] = useState(0.2);

  const [memoryKind, setMemoryKind] = useState("preference");
  const [memoryText, setMemoryText] = useState("");

  useEffect(() => {
    const p = policy.data;
    if (!p) return;
    setReserve(String(p.cash_reserve_minimum_paise ?? 0));
    setRefundMax(String(p.automatic_refund_maximum_paise ?? 0));
    setPayoutLimit(String(p.payout_automatic_limit_paise ?? 0));
    setAutonomy(p.autonomy_level || "recommend");
    setGrowth(Number(p.weights?.growth ?? 0.3));
    setCash(Number(p.weights?.cash ?? 0.5));
    setRisk(Number(p.weights?.risk ?? 0.2));
  }, [policy.data]);

  const weightSum = growth + cash + risk;
  const rows: any[] = memories.data?.memories || [];

  async function save() {
    await run(
      "save",
      async () => {
        await brain.savePolicy({
          cash_reserve_minimum_paise: Math.round(Number(reserve) || 0),
          automatic_refund_maximum_paise: Math.round(Number(refundMax) || 0),
          payout_automatic_limit_paise: Math.round(Number(payoutLimit) || 0),
          autonomy_level: autonomy,
          weights: { growth, cash, risk },
        });
        await policy.reload();
      },
      "Policy saved. It applies to the next action the executor evaluates.",
    );
  }

  return (
    <>
      <PageHead
        title="Policy & memory"
        description="The constitution the safety kernel enforces, and the durable facts the copilot and agents are allowed to assume."
        actions={
          <button className="btn ghost sm" onClick={() => Promise.all([policy.reload(), memories.reload()])}>
            Refresh
          </button>
        }
      />
      <ErrorNote>{policy.error || memories.error || actionError}</ErrorNote>
      {message && <p className="notice">{message}</p>}

      <div className="grid g4">
        <StatCard label="Cash reserve floor" value={inr(policy.data?.cash_reserve_minimum_paise)} foot="Breaching this is the hard constraint" />
        <StatCard label="Auto-refund ceiling" value={inr(policy.data?.automatic_refund_maximum_paise)} foot="Above this, a human decides" />
        <StatCard label="Auto-payout limit" value={inr(policy.data?.payout_automatic_limit_paise)} foot="Above this, a human decides" />
        <StatCard
          label="Autonomy level"
          value={titleCase(policy.data?.autonomy_level)}
          tone={toneFor(policy.data?.autonomy_level === "autonomous" ? "high" : "medium")}
          foot={AUTONOMY.find((a) => a.value === policy.data?.autonomy_level)?.detail}
        />
      </div>

      <div className="grid split">
        <Card title="Edit policy" subtitle="Changes take effect on the next action the kernel evaluates.">
          <div className="grid g3">
            <label className="field">
              Cash reserve minimum (paise)
              <input type="number" min={0} value={reserve} onChange={(e) => setReserve(e.target.value)} />
              <span className="tiny">{inr(Number(reserve))}</span>
            </label>
            <label className="field">
              Automatic refund maximum (paise)
              <input type="number" min={0} value={refundMax} onChange={(e) => setRefundMax(e.target.value)} />
              <span className="tiny">{inr(Number(refundMax))}</span>
            </label>
            <label className="field">
              Automatic payout limit (paise)
              <input type="number" min={0} value={payoutLimit} onChange={(e) => setPayoutLimit(e.target.value)} />
              <span className="tiny">{inr(Number(payoutLimit))}</span>
            </label>
          </div>

          <div className="card-title" style={{ margin: "18px 0 8px" }}>
            Autonomy
          </div>
          <div className="stack-v" style={{ gap: 6 }}>
            {AUTONOMY.map((option) => (
              <label key={option.value} className="checkbox" style={{ alignItems: "flex-start" }}>
                <input
                  type="radio"
                  name="autonomy"
                  checked={autonomy === option.value}
                  onChange={() => setAutonomy(option.value)}
                />
                <span>
                  <strong style={{ fontSize: 12.5 }}>{option.label}</strong>
                  <div className="tiny">{option.detail}</div>
                </span>
              </label>
            ))}
          </div>

          <div className="card-title" style={{ margin: "18px 0 8px" }}>
            Objective weights
          </div>
          <p className="tiny" style={{ marginBottom: 8 }}>
            These weight the orchestrator's scoring function. They do not need to sum to one, but the ratio is what
            matters — currently {weightSum.toFixed(2)} in total.
          </p>
          <div className="stack-v">
            {[
              ["Growth", growth, setGrowth, "Recovered GMV"],
              ["Cash", cash, setCash, "Projected cash impact"],
              ["Risk", risk, setRisk, "Penalty on breach probability"],
            ].map(([label, value, setter, hint]: any) => (
              <label key={label} className="stack-v" style={{ gap: 4 }}>
                <div className="spread" style={{ fontSize: 12.5 }}>
                  <span>
                    {label} <span className="tiny">{hint}</span>
                  </span>
                  <strong className="num">{Number(value).toFixed(2)}</strong>
                </div>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={value}
                  onChange={(e) => setter(Number(e.target.value))}
                  style={{ padding: 0, background: "transparent", border: 0, accentColor: "var(--brand)" }}
                />
              </label>
            ))}
          </div>

          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn" disabled={!!busy} onClick={save}>
              {busy === "save" ? "Saving…" : "Save policy"}
            </button>
            <button className="btn ghost" onClick={() => policy.reload()}>
              Discard changes
            </button>
          </div>
        </Card>

        <Card title="Stored policy record" subtitle="Exactly what the kernel reads.">
          <Json value={policy.data} maxHeight={420} />
        </Card>
      </div>

      <Card title="Action risk ladder" subtitle="What each action type costs in policy terms, and when approval kicks in.">
        <DataTable
          rows={LEVELS.map(([type, level, label]) => ({ type, level, label }))}
          rowKey={(row) => row.type}
          columns={[
            { key: "type", header: "Action", render: (row) => <span className="mono">{row.type}</span> },
            { key: "level", header: "Level", align: "right" },
            {
              key: "label",
              header: "Class",
              render: (row) => (
                <Badge tone={row.level >= 3 ? "critical" : row.level === 2 ? "warning" : "good"}>{row.label}</Badge>
              ),
            },
            {
              key: "gate",
              header: "Under current autonomy",
              render: (row) => {
                const max = { observe: 0, recommend: 1, draft: 1, bounded: 2, autonomous: 3 }[autonomy] ?? 1;
                if (row.level >= 3) return <span className="tiny">always needs approval</span>;
                return row.level <= max ? (
                  <span className="tiny">may run unattended</span>
                ) : (
                  <span className="tiny">needs approval</span>
                );
              },
            },
          ]}
        />
      </Card>

      <div className="grid split">
        <Card title="Merchant memory" subtitle="Durable facts the copilot may assume without re-deriving them.">
          <DataTable
            rows={rows}
            rowKey={(row) => row.memory_id}
            columns={[
              { key: "kind", header: "Kind", render: (row) => <Badge tone="neutral">{row.kind}</Badge> },
              { key: "text", header: "Memory" },
              { key: "source", header: "Source", render: (row) => <span className="tiny">{row.source}</span> },
              { key: "created_at", header: "Added", render: (row) => relativeTime(row.created_at) },
            ]}
            empty="No memories stored."
          />
        </Card>

        <Card title="Add a memory" subtitle="Anything you tell the brain here survives restarts and informs every future answer.">
          <div className="stack-v">
            <label className="field">
              Kind
              <select value={memoryKind} onChange={(e) => setMemoryKind(e.target.value)}>
                {MEMORY_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {kind}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Memory
              <textarea
                rows={4}
                value={memoryText}
                onChange={(e) => setMemoryText(e.target.value)}
                placeholder="e.g. Diwali week always doubles UPI volume; do not treat the spike as fraud."
              />
            </label>
            <button
              className="btn"
              disabled={!!busy || !memoryText.trim()}
              onClick={() =>
                run(
                  "memory",
                  async () => {
                    await brain.addMemory(memoryKind, memoryText.trim());
                    setMemoryText("");
                    await memories.reload();
                  },
                  "Memory stored.",
                )
              }
            >
              {busy === "memory" ? "Storing…" : "Store memory"}
            </button>
            <p className="tiny">
              Memories are retrieved by token overlap when the copilot answers, so write them the way you would say them.
            </p>
          </div>
        </Card>
      </div>
    </>
  );
}
