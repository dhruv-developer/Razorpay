"use client";

import { useState } from "react";
import { PageHead } from "@/components/Shell";
import { BarList, ChartFrame, SERIES } from "@/components/charts";
import { Badge, Card, DataTable, Drawer, Empty, ErrorNote, Json, KeyValues, Meter, StatCard } from "@/components/ui";
import { brain } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { dateTime, inr, inrExact, num, pct, relativeTime, titleCase, toneFor } from "@/lib/format";

export default function AgentsPage() {
  const agents = useResource(() => brain.adminAgents(), []);
  const { busy, error: actionError, run } = useAction();
  const [proposal, setProposal] = useState<any>(null);
  const [openRun, setOpenRun] = useState<any>(null);

  const registry: any[] = agents.data?.registry || [];
  const leaderboard: any[] = agents.data?.leaderboard || [];
  const runs: any[] = agents.data?.runs || [];
  const breakers: any[] = agents.data?.circuit_breakers || [];

  const totalOutcomes = leaderboard.reduce((sum, a) => sum + a.outcomes, 0);
  const netImpact = leaderboard.reduce((sum, a) => sum + a.net_impact_paise, 0);
  const tripped = breakers.filter((b) => b.tripped);

  return (
    <>
      <PageHead
        title="Agents & trust"
        description="Four specialist agents bid, the orchestrator scores them under the merchant's own objective weights, and trust moves only on verified outcomes."
        actions={
          <>
            <button
              className="btn ghost"
              disabled={!!busy}
              onClick={() => run("orch", async () => {
                await brain.orchestrate();
                await agents.reload();
              }, "Orchestration run recorded.")}
            >
              {busy === "orch" ? "Running…" : "Run orchestration"}
            </button>
            <button className="btn ghost sm" onClick={agents.reload}>
              Refresh
            </button>
          </>
        }
      />
      <ErrorNote>{agents.error || actionError}</ErrorNote>

      <div className="grid g4">
        <StatCard label="Registered agents" value={registry.length} foot="Each declares its own capabilities" />
        <StatCard label="Proposals recorded" value={num(runs.length)} foot="Every bid is persisted, winner or not" />
        <StatCard label="Verified outcomes" value={num(totalOutcomes)} foot="Only these move trust" />
        <StatCard
          label="Circuit breakers"
          value={tripped.length ? `${tripped.length} tripped` : "All clear"}
          tone={tripped.length ? "critical" : "good"}
          foot={`${breakers.length} tracked`}
        />
      </div>

      <div className="grid g2">
        {registry.map((agent) => {
          const stats = leaderboard.find((a) => a.agent_id === agent.agent_id) || {};
          return (
            <Card
              key={agent.agent_id}
              title={titleCase(agent.agent_id)}
              subtitle={agent.capabilities.join(" · ")}
              actions={
                <>
                  <Badge tone={toneFor(stats.autonomy)}>{titleCase(stats.autonomy || "recommend")}</Badge>
                  <button
                    className="btn ghost xs"
                    disabled={!!busy}
                    onClick={() =>
                      run(`propose-${agent.agent_id}`, async () => {
                        const res: any = await brain.agentPropose(agent.agent_id);
                        setProposal({ agent_id: agent.agent_id, ...res });
                      })
                    }
                  >
                    {busy === `propose-${agent.agent_id}` ? "Asking…" : "Ask for a proposal"}
                  </button>
                </>
              }
            >
              <div className="stack-v" style={{ gap: 8 }}>
                <div className="stack-v" style={{ gap: 4 }}>
                  <div className="spread tiny">
                    <span>Trust</span>
                    <span className="num">{pct(stats.trust)}</span>
                  </div>
                  <Meter value={Number(stats.trust || 0)} tone={Number(stats.trust) > 0.6 ? "good" : "warning"} />
                </div>
                <div className="stack-v" style={{ gap: 4 }}>
                  <div className="spread tiny">
                    <span>Calibration</span>
                    <span className="num">{pct(stats.calibration)}</span>
                  </div>
                  <Meter value={Number(stats.calibration || 0)} />
                </div>
                <div className="grid g4" style={{ gap: 8, marginTop: 4 }}>
                  <Mini label="Proposals" value={num(stats.proposals || 0)} />
                  <Mini label="Actions" value={num(stats.actions || 0)} />
                  <Mini label="Succeeded" value={num(stats.successful_actions || 0)} />
                  <Mini label="Failed" value={num(stats.failed_actions || 0)} />
                </div>
                <div className="spread tiny" style={{ marginTop: 4 }}>
                  <span>Net measured impact</span>
                  <strong className="num">{inr(stats.net_impact_paise || 0)}</strong>
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      <div className="grid split">
        <ChartFrame
          title="Net impact by agent"
          subtitle="Measured after execution, not the estimate."
          stale={agents.refreshing}
          table={{
            columns: ["Agent", "Net impact", "Outcomes", "Trust"],
            rows: leaderboard.map((a) => [titleCase(a.agent_id), inrExact(a.net_impact_paise), num(a.outcomes), pct(a.trust)]),
          }}
        >
          <BarList
            items={leaderboard.map((a) => ({ key: a.agent_id, label: titleCase(a.agent_id), value: a.net_impact_paise }))}
            format={inr}
            meta={(item) => <span className="tiny">{num(leaderboard.find((a) => a.agent_id === item.key)?.outcomes)} outcomes</span>}
          />
        </ChartFrame>

        <ChartFrame
          title="Trust by agent"
          subtitle="Decays every update; rises only on a verified action."
          stale={agents.refreshing}
          table={{
            columns: ["Agent", "Trust", "Autonomy", "Violations"],
            rows: leaderboard.map((a) => [titleCase(a.agent_id), pct(a.trust), titleCase(a.autonomy), num(a.policy_violations)]),
          }}
        >
          <BarList
            items={leaderboard.map((a) => ({ key: a.agent_id, label: titleCase(a.agent_id), value: a.trust }))}
            format={(v) => pct(v)}
            color={SERIES[2]}
            meta={(item) => (
              <Badge tone={toneFor(leaderboard.find((a) => a.agent_id === item.key)?.autonomy)}>
                {titleCase(leaderboard.find((a) => a.agent_id === item.key)?.autonomy)}
              </Badge>
            )}
          />
        </ChartFrame>
      </div>

      <Card title="Proposal log" subtitle="Every bid an agent made, whether or not it won. Click for the full record.">
        <DataTable
          rows={runs}
          rowKey={(row) => row.run_id}
          onRowClick={setOpenRun}
          columns={[
            { key: "agent_id", header: "Agent", render: (row) => <strong>{titleCase(row.agent_id)}</strong> },
            {
              key: "type",
              header: "Proposed",
              render: (row) => <span className="mono">{row.proposal?.proposal?.type || "—"}</span>,
            },
            {
              key: "amount",
              header: "Amount",
              align: "right",
              render: (row) => inrExact(row.proposal?.proposal?.amount_paise || 0),
            },
            {
              key: "confidence",
              header: "Confidence",
              align: "right",
              render: (row) => pct(row.proposal?.confidence),
            },
            {
              key: "reversibility",
              header: "Reversibility",
              render: (row) => titleCase(row.proposal?.reversibility),
            },
            {
              key: "reason",
              header: "Reason",
              render: (row) => <span className="tiny">{row.proposal?.proposal?.reason}</span>,
            },
            { key: "created_at", header: "When", render: (row) => relativeTime(row.created_at) },
          ]}
          empty="No proposals recorded yet. Run an orchestration."
        />
      </Card>

      <Card title="Circuit breakers" subtitle="Per agent, per action type, counted over a rolling ten-minute window.">
        {breakers.length ? (
          <DataTable
            rows={breakers}
            rowKey={(row, i) => `${row.agent_id}-${row.action_type}-${i}`}
            columns={[
              { key: "agent_id", header: "Agent", render: (row) => titleCase(row.agent_id) },
              { key: "action_type", header: "Action", render: (row) => <span className="mono">{row.action_type}</span> },
              { key: "window_count", header: "In window", align: "right" },
              { key: "limit", header: "Limit", align: "right" },
              {
                key: "tripped",
                header: "State",
                render: (row) => <Badge tone={row.tripped ? "critical" : "good"}>{row.tripped ? "Tripped" : "Armed"}</Badge>,
              },
              { key: "updated_at", header: "Checked", render: (row) => dateTime(row.updated_at) },
            ]}
          />
        ) : (
          <Empty title="No breaker has been evaluated yet" hint="They arm the first time an agent tries to execute." />
        )}
      </Card>

      <Drawer
        open={!!proposal}
        title={`${titleCase(proposal?.agent_id)} proposal`}
        subtitle="Asked live — nothing was created or executed."
        onClose={() => setProposal(null)}
      >
        {proposal &&
          (proposal.proposal ? (
            <>
              <KeyValues
                rows={[
                  ["Action", <span className="mono">{proposal.proposal.proposal?.type}</span>],
                  ["Amount", inrExact(proposal.proposal.proposal?.amount_paise)],
                  ["Confidence", pct(proposal.proposal.confidence)],
                  ["Reversibility", titleCase(proposal.proposal.reversibility)],
                  ["Permissions", (proposal.proposal.required_permissions || []).join(", ")],
                  ["Evidence", <span className="mono">{(proposal.proposal.evidence_ids || []).join(", ")}</span>],
                  ["Reason", proposal.proposal.proposal?.reason],
                ]}
              />
              <Json value={proposal.proposal} />
            </>
          ) : (
            <Empty title="This agent abstained" hint="Nothing in the current state meets its trigger conditions." />
          ))}
      </Drawer>

      <Drawer open={!!openRun} title={titleCase(openRun?.agent_id)} subtitle={openRun?.run_id} onClose={() => setOpenRun(null)}>
        {openRun && <Json value={openRun} maxHeight={100000} />}
      </Drawer>
    </>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="stack-v" style={{ gap: 1 }}>
      <span className="tiny">{label}</span>
      <strong className="num" style={{ fontSize: 14 }}>
        {value}
      </strong>
    </div>
  );
}
