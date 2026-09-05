"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { PageHead } from "@/components/Shell";
import { Badge, Card, Empty, ErrorNote, Json, KeyValues } from "@/components/ui";
import { brain } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { dateTime, titleCase } from "@/lib/format";

type Turn = { role: "me" | "brain"; text: string; meta?: any; at: string };

const SUGGESTIONS = [
  "Why is my cash falling?",
  "Why did revenue drop today?",
  "Where is my money?",
  "What should I do right now?",
  "What happens if I do nothing?",
  "Which payment method is failing most?",
];

export default function CopilotPage() {
  const system = useResource(() => brain.system(), []);
  const [message, setMessage] = useState("Why is my cash falling?");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  const llm = system.data?.dependencies?.llm;
  const last = [...turns].reverse().find((t) => t.role === "brain" && t.meta);

  async function send(event: FormEvent) {
    event.preventDefault();
    const question = message.trim();
    if (!question || busy) return;
    setTurns((current) => [...current, { role: "me", text: question, at: new Date().toISOString() }]);
    setMessage("");
    setBusy(true);
    setError("");
    try {
      const res: any = await brain.ask(question);
      setTurns((current) => [
        ...current,
        {
          role: "brain",
          text: res.response?.answer || "No grounded answer was produced.",
          meta: res,
          at: new Date().toISOString(),
        },
      ]);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHead
        title="Business copilot"
        description="The model only words what the tools returned. It reads structured evidence; it cannot move money or invent a number."
        actions={
          llm ? (
            <Badge tone={llm.configured ? "good" : "warning"}>
              {llm.configured ? `${llm.model} connected` : "Deterministic fallback"}
            </Badge>
          ) : null
        }
      />
      {llm && !llm.configured && <p className="notice">{llm.detail}</p>}
      <ErrorNote>{error}</ErrorNote>

      <div className="grid split">
        <Card title="Conversation" subtitle="Each answer carries the tools it called and the evidence ids behind each claim.">
          <div className="chat" style={{ minHeight: 260, maxHeight: 460, overflowY: "auto", paddingRight: 4 }}>
            {turns.length === 0 && (
              <Empty title="Ask anything about this merchant" hint="Every answer is grounded in the world model below." />
            )}
            {turns.map((turn, index) => (
              <div key={index} className={`bubble ${turn.role === "me" ? "me" : ""}`}>
                {turn.text}
                {turn.meta?.response?.claims?.length ? (
                  <div className="stack-v" style={{ marginTop: 9, gap: 4 }}>
                    {turn.meta.response.claims.map((claim: any, claimIndex: number) => (
                      <div key={claimIndex} className="tiny">
                        · {claim.claim}{" "}
                        <span className="mono">{(claim.evidence_ids || []).join(", ")}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
                {turn.meta?.context_keys?.length ? (
                  <div className="row tight" style={{ marginTop: 8 }}>
                    {turn.meta.context_keys.map((key: string) => (
                      <Badge key={key} tone="brand" glyph={false}>
                        {key}
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
            {busy && <div className="bubble">Reading the world model…</div>}
            <div ref={endRef} />
          </div>

          <form onSubmit={send} className="row" style={{ marginTop: 14, flexWrap: "nowrap" }}>
            <input
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Ask about cash, failures, receivables, disputes…"
              aria-label="Question"
            />
            <button className="btn" disabled={busy} type="submit">
              {busy ? "Thinking…" : "Ask"}
            </button>
          </form>
          <div className="row tight" style={{ marginTop: 10 }}>
            {SUGGESTIONS.map((suggestion) => (
              <button key={suggestion} className="btn subtle xs" type="button" onClick={() => setMessage(suggestion)}>
                {suggestion}
              </button>
            ))}
          </div>
        </Card>

        <div className="stack-v">
          <Card title="Grounding for the last answer" subtitle="Exactly what the model was allowed to see.">
            {last?.meta ? (
              <>
                <KeyValues
                  rows={[
                    ["Intent", titleCase(last.meta.intent)],
                    ["Tools called", (last.meta.context_keys || []).join(", ") || "—"],
                    ["Claims", (last.meta.response?.claims || []).length],
                    ["Trace", <span className="mono">{last.meta.trace_id}</span>],
                    ["Answered", dateTime(last.at)],
                  ]}
                />
                <div style={{ marginTop: 12 }}>
                  <Json value={last.meta} maxHeight={320} />
                </div>
              </>
            ) : (
              <Empty title="Nothing asked yet" />
            )}
          </Card>

          <Card title="Guardrails" subtitle="Why this copilot cannot hallucinate a number.">
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: "var(--ink-2)", display: "grid", gap: 6 }}>
              <li>The model receives tool output only — never raw collections or free-form context.</li>
              <li>Every claim must carry evidence ids that resolve to a feature, state field or collection.</li>
              <li>It has no write tools: it can explain an action, it cannot create or approve one.</li>
              <li>PII is stripped before anything leaves the process.</li>
              <li>With no API key configured, answers fall back to deterministic templates over the same evidence.</li>
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}
