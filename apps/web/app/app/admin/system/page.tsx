"use client";

import { PageHead } from "@/components/Shell";
import { Badge, Card, DataTable, ErrorNote, Json, KeyValues, Skeleton, StatCard } from "@/components/ui";
import { brain } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { dateTime, num, relativeTime, titleCase } from "@/lib/format";

export default function SystemPage() {
  const system = useResource(() => brain.system(), []);

  const d = system.data;
  const deps = d?.dependencies || {};
  const collections: any[] = d?.collections || [];
  const populated = collections.filter((c) => c.merchant_documents > 0);
  const totalDocs = collections.reduce((sum, c) => sum + c.merchant_documents, 0);
  const healthy = [deps.mongo?.connected, deps.redis?.connected].filter(Boolean).length;

  return (
    <>
      <PageHead
        title="System"
        description="Service health, configuration and storage — everything the console depends on, reported by the API itself."
        actions={
          <button className="btn ghost sm" onClick={system.reload} disabled={system.refreshing}>
            {system.refreshing ? "Refreshing…" : "Refresh"}
          </button>
        }
      />
      <ErrorNote>{system.error}</ErrorNote>

      {system.loading ? (
        <div className="grid g4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} height={104} />
          ))}
        </div>
      ) : (
        <div className="grid g4">
          <StatCard
            label="Dependencies healthy"
            value={`${healthy} / 2`}
            tone={healthy === 2 ? "good" : "critical"}
            foot="Mongo and Redis"
          />
          <StatCard label="Uptime" value={formatUptime(d?.uptime_seconds)} foot={`Started ${dateTime(d?.started_at)}`} />
          <StatCard label="Documents (this merchant)" value={num(totalDocs)} foot={`${populated.length} populated collections`} />
          <StatCard
            label="Last event"
            value={d?.last_event_at ? relativeTime(d.last_event_at) : "—"}
            foot={d?.last_state_at ? `state recomputed ${relativeTime(d.last_state_at)}` : undefined}
          />
        </div>
      )}

      <div className="grid g3">
        <Card
          title="MongoDB"
          subtitle="Primary store for every collection."
          actions={<Badge tone={deps.mongo?.connected ? "good" : "critical"}>{deps.mongo?.connected ? "Connected" : "Down"}</Badge>}
        >
          <KeyValues
            rows={[
              ["Database", d?.config?.mongo_db],
              ["Ping latency", deps.mongo?.latency_ms ? `${deps.mongo.latency_ms} ms` : "—"],
              ["Error", deps.mongo?.error || "none"],
            ]}
          />
        </Card>
        <Card
          title="Redis"
          subtitle="Idempotency claims, locks and cache."
          actions={<Badge tone={deps.redis?.connected ? "good" : "warning"}>{deps.redis?.connected ? "Connected" : "Degraded"}</Badge>}
        >
          <KeyValues
            rows={[
              ["Ping latency", deps.redis?.latency_ms ? `${deps.redis.latency_ms} ms` : "—"],
              ["Fallback", deps.redis?.connected ? "not needed" : "Mongo-only deduplication"],
              ["Detail", deps.redis?.detail || deps.redis?.error || "none"],
            ]}
          />
        </Card>
        <Card
          title="Language model"
          subtitle="Explanation only — it holds no write tools."
          actions={<Badge tone={deps.llm?.configured ? "good" : "warning"}>{deps.llm?.configured ? "Configured" : "Fallback"}</Badge>}
        >
          <KeyValues
            rows={[
              ["Provider", titleCase(deps.llm?.provider)],
              ["Model", <span className="mono">{deps.llm?.model}</span>],
              ["Detail", <span className="tiny">{deps.llm?.detail}</span>],
            ]}
          />
        </Card>
      </div>

      <div className="grid split">
        <Card title="Storage" subtitle="Documents per collection: total across the deployment, and this merchant's share.">
          <DataTable
            rows={collections}
            rowKey={(row) => row.name}
            columns={[
              { key: "name", header: "Collection", render: (row) => <span className="mono">{row.name}</span> },
              { key: "merchant_documents", header: "This merchant", align: "right", render: (row) => num(row.merchant_documents) },
              { key: "documents", header: "All merchants", align: "right", render: (row) => num(row.documents) },
              {
                key: "share",
                header: "",
                render: (row) =>
                  row.documents ? (
                    <div style={{ height: 6, background: "var(--surface-3)", borderRadius: 3, minWidth: 60 }}>
                      <div
                        style={{
                          width: `${(row.merchant_documents / row.documents) * 100}%`,
                          height: "100%",
                          background: "var(--s1)",
                          borderRadius: 3,
                        }}
                      />
                    </div>
                  ) : null,
              },
            ]}
          />
        </Card>

        <div className="stack-v">
          <Card title="Identity" subtitle="Who this console is acting as.">
            <KeyValues
              rows={[
                ["Merchant", d?.merchant?.name],
                ["Merchant id", <span className="mono">{d?.merchant?.merchant_id}</span>],
                ["Tenant id", <span className="mono">{d?.merchant?.tenant_id}</span>],
                ["Industry", titleCase(d?.merchant?.industry)],
                ["Active", d?.merchant?.active ? "yes" : "no"],
                ["User", d?.principal?.email],
                ["Roles", (d?.principal?.roles || []).join(", ")],
                ["Auth", titleCase(d?.principal?.type)],
              ]}
            />
          </Card>

          <Card title="Configuration" subtitle="Non-secret settings the API is running with.">
            <KeyValues
              rows={[
                ["Service", `${d?.service} v${d?.version}`],
                ["CORS origins", (d?.config?.cors_origins || []).join(", ")],
                ["Token lifetime", `${d?.config?.jwt_expire_minutes} minutes`],
                ["Seed on start", d?.config?.seed_on_start ? "yes" : "no"],
                ["Seed window", `${d?.config?.seed_days} days`],
              ]}
            />
            <p className="tiny" style={{ marginTop: 10 }}>
              Secrets — the JWT signing key, the Gemini API key and connection strings — are never sent to the browser.
            </p>
          </Card>

          <Card title="Active policy" subtitle="What the safety kernel is enforcing right now.">
            <Json value={d?.policy} maxHeight={220} />
          </Card>
        </div>
      </div>
    </>
  );
}

function formatUptime(seconds: number | undefined): string {
  const value = Number(seconds || 0);
  if (value < 60) return `${value.toFixed(0)}s`;
  if (value < 3600) return `${(value / 60).toFixed(0)}m`;
  if (value < 86400) return `${(value / 3600).toFixed(1)}h`;
  return `${(value / 86400).toFixed(1)}d`;
}
