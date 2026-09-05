"use client";

import { useState } from "react";
import { PageHead } from "@/components/Shell";
import { BarList, ChartFrame } from "@/components/charts";
import { Badge, Card, Drawer, Empty, ErrorNote, Json, KeyValues, Meter, StatCard } from "@/components/ui";
import { brain } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { inr, inrExact, pct, titleCase, toneFor } from "@/lib/format";

const FACTORS: [string, string, string][] = [
  ["urgency", "Urgency", "How fast this compounds if untouched"],
  ["confidence", "Confidence", "How much evidence backs the finding"],
  ["reversibility", "Reversibility", "How cheaply a wrong call can be undone"],
];

export default function AttentionPage() {
  const attention = useResource(() => brain.attention(), []);
  const why = useResource(() => brain.why(), []);
  const risks = useResource(() => brain.risks(), []);
  const { busy, error: actionError, run } = useAction();
  const [open, setOpen] = useState<any>(null);

  const items: any[] = attention.data?.items || [];
  const drivers: any[] = why.data?.primary_drivers || [];
  const edges: any[] = why.data?.edges || [];
  const maxScore = Math.max(...items.map((i) => Number(i.score) || 0), 1);

  return (
    <>
      <PageHead
        title="Needs your attention"
        description="Ranked by impact × urgency × confidence × reversibility, computed from live state — not a static rules list."
        actions={
          <button
            className="btn"
            disabled={busy === "cycle"}
            onClick={() =>
              run("cycle", async () => {
                await brain.cycle();
                await Promise.all([attention.reload(), why.reload(), risks.reload()]);
              })
            }
          >
            {busy === "cycle" ? "Recomputing…" : "Recompute"}
          </button>
        }
      />
      <ErrorNote>{attention.error || actionError}</ErrorNote>

      <div className="grid g4">
        <StatCard label="Open items" value={items.length} foot="Above the attention threshold" />
        <StatCard
          label="Impact at stake"
          value={inr(items.reduce((sum, i) => sum + Math.abs(Number(i.impact_paise) || 0), 0))}
          foot="Sum of ranked item impact"
        />
        <StatCard
          label="Operational risk"
          value={pct(risks.data?.operational_risk)}
          tone={Number(risks.data?.operational_risk) > 0.5 ? "critical" : "warning"}
          foot={`Fraud ${pct(risks.data?.fraud_risk)} · dispute ${pct(risks.data?.dispute_risk)}`}
        />
        <StatCard label="Open disputes" value={inr(risks.data?.open_disputes_paise)} foot="Money contested by customers" />
      </div>

      {items.length ? (
        <div className="grid g2">
          {items.map((item) => (
            <Card
              key={item.id}
              title={
                <span className="row tight">
                  <Badge tone={toneFor(item.severity)}>{titleCase(item.severity)}</Badge>
                  {item.title}
                </span>
              }
              actions={
                <button className="btn ghost xs" onClick={() => setOpen(item)}>
                  {item.cta || "Inspect"}
                </button>
              }
            >
              <p style={{ fontSize: 13, color: "var(--ink-2)" }}>{item.why}</p>
              <div className="spread" style={{ marginTop: 12 }}>
                <span className="tiny">Impact</span>
                <strong className="num">{inr(item.impact_paise)}</strong>
              </div>
              <div className="stack-v" style={{ marginTop: 8, gap: 6 }}>
                {FACTORS.map(([key, label, hint]) => (
                  <div key={key} className="stack-v" style={{ gap: 3 }}>
                    <div className="spread tiny" title={hint}>
                      <span>{label}</span>
                      <span className="num">{pct(item[key], 0)}</span>
                    </div>
                    <Meter value={Number(item[key] || 0)} />
                  </div>
                ))}
                <div className="stack-v" style={{ gap: 3 }}>
                  <div className="spread tiny">
                    <span>Rank score</span>
                    <span className="num">{(Number(item.score) / maxScore).toFixed(2)} of top</span>
                  </div>
                  <Meter value={Number(item.score) / maxScore} tone="brand" />
                </div>
              </div>
              <p className="tiny mono" style={{ marginTop: 10 }}>
                {(item.evidence_ids || []).join(" · ") || "no evidence ids"}
              </p>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <Empty
            title="Nothing crossed the attention threshold"
            hint="Reserve breach risk, failure-rate drift, receivables and settlement delay are all inside their bands."
          />
        </Card>
      )}

      <div className="grid split">
        <ChartFrame
          title="Causal drivers of cash"
          subtitle={why.data?.cash_story}
          stale={why.refreshing}
          table={{
            columns: ["Claim", "Impact", "Confidence", "Evidence"],
            rows: drivers.map((d) => [d.claim, inrExact(d.impact_paise), pct(d.confidence), (d.evidence_ids || []).join(", ")]),
          }}
        >
          <BarList
            items={drivers.map((d, i) => ({ key: `${i}`, label: d.claim, value: d.impact_paise }))}
            format={inr}
            meta={(_, index) => <span className="tiny">{pct(drivers[index]?.confidence)} conf</span>}
          />
        </ChartFrame>

        <Card
          title="Causal graph"
          subtitle="Domain edges whose strength is measured from this merchant's own series."
          stale={why.refreshing}
        >
          <div className="table-wrap" style={{ maxHeight: 330 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Edge</th>
                  <th className="right">Strength</th>
                  <th className="right">Conf.</th>
                  <th className="right">n</th>
                </tr>
              </thead>
              <tbody>
                {edges.map((edge) => (
                  <tr key={`${edge.source}->${edge.destination}`}>
                    <td>
                      <span className="mono">{edge.source}</span> → <span className="mono">{edge.destination}</span>
                      <br />
                      <span className="tiny">{titleCase(edge.relationship)}</span>
                    </td>
                    <td className="right" style={{ color: edge.strength < 0 ? "var(--critical)" : "var(--good)" }}>
                      {Number(edge.strength).toFixed(2)}
                    </td>
                    <td className="right">{pct(edge.confidence, 0)}</td>
                    <td className="right">{edge.samples}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Drawer
        open={!!open}
        title={open?.title || ""}
        subtitle={open ? `${titleCase(open.severity)} · impact ${inr(open.impact_paise)}` : undefined}
        onClose={() => setOpen(null)}
      >
        {open && (
          <>
            <p style={{ fontSize: 13 }}>{open.why}</p>
            <KeyValues
              rows={[
                ["Item id", <span className="mono">{open.id}</span>],
                ["Impact", inrExact(open.impact_paise)],
                ["Urgency", pct(open.urgency)],
                ["Confidence", pct(open.confidence)],
                ["Reversibility", pct(open.reversibility)],
                ["Rank score", Number(open.score).toExponential(3)],
                ["Evidence", <span className="mono">{(open.evidence_ids || []).join(", ")}</span>],
              ]}
            />
            <div>
              <div className="card-title" style={{ marginBottom: 6 }}>
                Raw item
              </div>
              <Json value={open} />
            </div>
          </>
        )}
      </Drawer>
    </>
  );
}
