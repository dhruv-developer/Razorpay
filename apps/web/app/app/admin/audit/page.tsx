"use client";

import { useMemo, useState } from "react";
import { PageHead } from "@/components/Shell";
import { BarList, ChartFrame, SERIES } from "@/components/charts";
import { Badge, Card, DataTable, Drawer, ErrorNote, Json, StatCard } from "@/components/ui";
import { brain } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { dateTime, num, relativeTime, titleCase, toneFor } from "@/lib/format";

export default function AuditPage() {
  const audit = useResource(() => brain.audit(200), []);
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<any>(null);

  const entries: any[] = audit.data?.entries || [];
  const byEvent: any[] = audit.data?.by_event || [];

  const rows = useMemo(
    () => (filter ? entries.filter((e) => e.event === filter) : entries),
    [entries, filter],
  );

  const actors = useMemo(() => {
    const counts = new Map<string, number>();
    for (const entry of entries) {
      const key = entry.actor || "system";
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return [...counts.entries()].map(([key, count]) => ({ key, label: key, value: count })).sort((a, b) => b.value - a.value);
  }, [entries]);

  return (
    <>
      <PageHead
        title="Audit trail"
        description="Immutable record of who or what did each thing. Action creation, verification, failure, copilot turns and admin self-tests all land here."
        actions={
          <>
            <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 220 }} aria-label="Filter by event">
              <option value="">All audit events</option>
              {byEvent.map((event) => (
                <option key={event.key} value={event.key}>
                  {event.key} ({event.count})
                </option>
              ))}
            </select>
            <button className="btn ghost sm" onClick={audit.reload} disabled={audit.refreshing}>
              {audit.refreshing ? "Refreshing…" : "Refresh"}
            </button>
          </>
        }
      />
      <ErrorNote>{audit.error}</ErrorNote>

      <div className="grid g4">
        <StatCard label="Entries loaded" value={num(entries.length)} foot="Most recent first" />
        <StatCard label="Distinct events" value={num(byEvent.length)} />
        <StatCard label="Distinct actors" value={num(actors.length)} foot="Users, agents and the executor" />
        <StatCard label="Latest" value={entries[0] ? relativeTime(entries[0].created_at) : "—"} foot={entries[0]?.event} />
      </div>

      <div className="grid split">
        <ChartFrame
          title="Audit events by kind"
          subtitle="What the system spends its writes on."
          stale={audit.refreshing}
          table={{ columns: ["Event", "Count"], rows: byEvent.map((e) => [e.key, num(e.count)]) }}
        >
          <BarList
            items={byEvent.map((e) => ({ key: e.key, label: e.key, value: e.count }))}
            format={num}
          />
        </ChartFrame>

        <ChartFrame
          title="By actor"
          subtitle="Who initiated each recorded step."
          stale={audit.refreshing}
          table={{ columns: ["Actor", "Entries"], rows: actors.map((a) => [a.label, num(a.value)]) }}
        >
          <BarList items={actors} format={num} color={SERIES[2]} />
        </ChartFrame>
      </div>

      <Card
        title="Trail"
        subtitle={filter ? `Filtered to ${filter}.` : "Every recorded step, newest first."}
        stale={audit.refreshing}
      >
        <DataTable
          rows={rows}
          rowKey={(row, index) => `${row.action_id || row.copilot_id || "entry"}-${index}`}
          onRowClick={setOpen}
          columns={[
            {
              key: "event",
              header: "Event",
              render: (row) => (
                <Badge tone={toneFor(row.event?.includes("failed") ? "failed" : row.event?.includes("verified") ? "verified" : "neutral")}>
                  {row.event || "copilot.turn"}
                </Badge>
              ),
            },
            {
              key: "subject",
              header: "Subject",
              render: (row) => <span className="mono cell-clip">{row.action_id || row.copilot_id || "—"}</span>,
            },
            { key: "actor", header: "Actor", render: (row) => <span className="mono">{row.actor || "system"}</span> },
            {
              key: "detail",
              header: "Detail",
              render: (row) => (
                <span className="cell-clip tiny" title={JSON.stringify(row.detail || row.response || {})}>
                  {summarise(row)}
                </span>
              ),
            },
            { key: "created_at", header: "When", render: (row) => dateTime(row.created_at) },
          ]}
          empty="No audit entries."
        />
      </Card>

      <Drawer
        open={!!open}
        title={open?.event || "Audit entry"}
        subtitle={open ? dateTime(open.created_at) : undefined}
        onClose={() => setOpen(null)}
      >
        {open && <Json value={open} maxHeight={100000} />}
      </Drawer>
    </>
  );
}

function summarise(row: any): string {
  if (row.detail?.summary) {
    const s = row.detail.summary;
    return `${s.passed}/${s.total} checks passed${s.failed ? `, ${s.failed} failed` : ""}`;
  }
  if (row.detail?.detail) return String(row.detail.detail);
  if (row.detail?.requires_approval !== undefined)
    return row.detail.requires_approval ? "approval required" : "auto-authorised";
  if (row.message) return `copilot: ${row.message}`;
  return row.detail ? JSON.stringify(row.detail) : "—";
}
