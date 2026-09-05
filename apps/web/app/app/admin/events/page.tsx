"use client";

import { useState } from "react";
import { PageHead } from "@/components/Shell";
import { BarList, ChartFrame, LineChart, SERIES } from "@/components/charts";
import { Badge, Card, DataTable, Drawer, ErrorNote, Json, KeyValues, StatCard } from "@/components/ui";
import { EVENT_TYPES, brain } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { dateTime, inr, num, relativeTime, shortDate, titleCase } from "@/lib/format";

const PRESETS: { label: string; event_type: string; payload: Record<string, unknown>; note: string }[] = [
  {
    label: "Captured payment",
    event_type: "payment.captured",
    payload: { amount: 2500000, method: "upi", channel: "web" },
    note: "Raises GMV and the success rate; recomputes features and state.",
  },
  {
    label: "Failed payment",
    event_type: "payment.failed",
    payload: { amount: 2500000, method: "upi", channel: "web", failure_code: "BANK_DECLINE" },
    note: "Pushes the 24h failure rate up — enough of these trip the anomaly detector.",
  },
  {
    label: "Delayed settlement",
    event_type: "settlement.delayed",
    payload: { amount: 50000000, delay_hours: 24 },
    note: "Holds cash out of the account and drops settlement health.",
  },
  {
    label: "Overdue invoice",
    event_type: "invoice.overdue",
    payload: { amount: 15000000 },
    note: "Adds to overdue receivables, which wakes the receivables agent.",
  },
  {
    label: "New dispute",
    event_type: "dispute.created",
    payload: { amount: 900000, reason: "chargeback" },
    note: "Raises dispute risk and open contested money.",
  },
  {
    label: "Scheduled payout",
    event_type: "payout.created",
    payload: { amount: 80000000 },
    note: "A committed outflow — large enough and the cashflow agent proposes a delay.",
  },
];

export default function EventsPage() {
  const [filter, setFilter] = useState("");
  const events = useResource(() => brain.events({ event_type: filter || undefined, limit: 200 }), [filter]);
  const analytics = useResource(() => brain.analytics(30), []);
  const { busy, error: actionError, message, run } = useAction();
  const [open, setOpen] = useState<any>(null);

  const [eventType, setEventType] = useState<string>("payment.failed");
  const [entityId, setEntityId] = useState("");
  const [payload, setPayload] = useState('{\n  "amount": 2500000,\n  "method": "upi"\n}');
  const [payloadError, setPayloadError] = useState("");

  const rows: any[] = events.data?.events || [];
  const stats = analytics.data?.events || {};

  async function ingest(type: string, body: Record<string, unknown>, id?: string) {
    setPayloadError("");
    await run(
      "ingest",
      async () => {
        await brain.ingest({
          event_type: type,
          entity_id: id || `test_${type.replace(/\./g, "_")}_${Date.now()}`,
          source: "admin-console",
          payload: body,
        });
        await Promise.all([events.reload(), analytics.reload()]);
      },
      `Ingested ${type}. Features and world state were recomputed.`,
    );
  }

  function submitCustom() {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(payload);
    } catch (err: any) {
      setPayloadError(`Payload is not valid JSON: ${err.message}`);
      return;
    }
    void ingest(eventType, parsed, entityId || undefined);
  }

  return (
    <>
      <PageHead
        title="Events"
        description="The append-only ledger everything else is derived from. Ingesting here runs the real pipeline: entity resolution, feature recompute, state recompute."
        actions={
          <>
            <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 210 }} aria-label="Filter by event type">
              <option value="">All event types</option>
              {EVENT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
            <button className="btn ghost sm" onClick={events.reload} disabled={events.refreshing}>
              {events.refreshing ? "Refreshing…" : "Refresh"}
            </button>
          </>
        }
      />
      <ErrorNote>{events.error || actionError || payloadError}</ErrorNote>
      {message && <p className="notice">{message}</p>}

      <div className="grid g4">
        <StatCard label="Events ingested" value={num(stats.total)} foot="All time, this merchant" />
        <StatCard label="Distinct types" value={num((stats.by_type || []).length)} foot="Out of 29 supported" />
        <StatCard label="Showing" value={num(rows.length)} foot={filter || "all types"} />
        <StatCard label="Most recent" value={rows[0] ? relativeTime(rows[0].timestamp) : "—"} foot={rows[0]?.event_type} />
      </div>

      <Card
        title="Inject a test event"
        subtitle="These go through the same ingestion path as production traffic — idempotent, entity-resolved, and immediately reflected in state."
      >
        <div className="row" style={{ gap: 8, marginBottom: 14 }}>
          {PRESETS.map((preset) => (
            <button
              key={preset.label}
              className="btn subtle sm"
              disabled={!!busy}
              title={preset.note}
              onClick={() => ingest(preset.event_type, preset.payload)}
            >
              {preset.label}
              <span className="tiny">{inr(Number(preset.payload.amount || 0))}</span>
            </button>
          ))}
        </div>
        <div className="grid g3" style={{ alignItems: "start" }}>
          <label className="field">
            Event type
            <select value={eventType} onChange={(e) => setEventType(e.target.value)}>
              {EVENT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Entity id (blank to generate)
            <input value={entityId} onChange={(e) => setEntityId(e.target.value)} placeholder="pay_… / inv_… / setl_…" />
          </label>
          <label className="field">
            Payload (JSON)
            <textarea rows={4} value={payload} onChange={(e) => setPayload(e.target.value)} className="mono" />
          </label>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" disabled={!!busy} onClick={submitCustom}>
            {busy === "ingest" ? "Ingesting…" : "Ingest event"}
          </button>
          <span className="tiny">
            Amounts are integer paise. Replaying an event id returns <span className="mono">duplicate</span> instead of
            double-counting.
          </span>
        </div>
      </Card>

      <div className="grid split">
        <ChartFrame
          title="Ingestion volume"
          subtitle="Events per day across every source."
          stale={analytics.refreshing}
          table={{
            columns: ["Date", "Events"],
            rows: [...(stats.daily || [])].reverse().map((d: any) => [d.date, num(d.count)]),
          }}
        >
          <LineChart
            points={stats.daily || []}
            xKey="date"
            series={[{ key: "count", label: "Events" }]}
            format={num}
            xFormat={shortDate}
            area
          />
        </ChartFrame>

        <ChartFrame
          title="Events by source"
          subtitle="Seed data, live API traffic, the executor and this console."
          stale={analytics.refreshing}
          table={{
            columns: ["Source", "Events"],
            rows: (stats.by_source || []).map((s: any) => [s.key, num(s.count)]),
          }}
        >
          <BarList
            items={(stats.by_source || []).map((s: any) => ({ key: s.key, label: s.key, value: s.count }))}
            format={num}
            color={SERIES[2]}
          />
        </ChartFrame>
      </div>

      <Card title="Event stream" subtitle="Newest first. Click a row for the full envelope.">
        <DataTable
          rows={rows}
          rowKey={(row) => row.event_id}
          onRowClick={setOpen}
          columns={[
            { key: "event_type", header: "Type", render: (row) => <span className="mono">{row.event_type}</span> },
            { key: "entity_id", header: "Entity", render: (row) => <span className="mono cell-clip">{row.entity_id}</span> },
            {
              key: "amount",
              header: "Amount",
              align: "right",
              render: (row) => (row.payload?.amount ? inr(row.payload.amount) : <span className="tiny">—</span>),
            },
            { key: "source", header: "Source", render: (row) => <Badge tone="neutral">{row.source}</Badge> },
            { key: "timestamp", header: "When", render: (row) => dateTime(row.timestamp) },
            { key: "trace_id", header: "Trace", render: (row) => <span className="mono cell-clip">{row.trace_id}</span> },
          ]}
          empty="No events match this filter."
        />
      </Card>

      <Drawer
        open={!!open}
        title={open?.event_type || ""}
        subtitle={open ? `${open.event_id} · ${dateTime(open.timestamp)}` : undefined}
        onClose={() => setOpen(null)}
      >
        {open && (
          <>
            <KeyValues
              rows={[
                ["Entity", <span className="mono">{open.entity_id}</span>],
                ["Source", open.source],
                ["Version", open.event_version],
                ["Trace", <span className="mono">{open.trace_id}</span>],
                ["Timestamp", dateTime(open.timestamp)],
                ["Ingested", dateTime(open.ingested_at)],
              ]}
            />
            <div>
              <div className="card-title" style={{ marginBottom: 6 }}>
                Payload
              </div>
              <Json value={open.payload} />
            </div>
            <div>
              <div className="card-title" style={{ marginBottom: 6 }}>
                Full envelope
              </div>
              <Json value={open} />
            </div>
          </>
        )}
      </Drawer>
    </>
  );
}
