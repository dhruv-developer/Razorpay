export function rupees(paise: number | null | undefined): number {
  return Math.round((Number(paise || 0) / 100) * 100) / 100;
}

/** Compact INR in the Indian numbering system (K / L / Cr). */
export function inr(paise: number | null | undefined): string {
  const value = rupees(paise);
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_00_00_000) return `${sign}₹${(abs / 1_00_00_000).toFixed(2)}Cr`;
  if (abs >= 1_00_000) return `${sign}₹${(abs / 1_00_000).toFixed(2)}L`;
  if (abs >= 1_000) return `${sign}₹${(abs / 1_000).toFixed(1)}K`;
  return `${sign}₹${abs.toFixed(abs % 1 === 0 ? 0 : 2)}`;
}

/** Full precision INR, for tables and tooltips where the exact figure matters. */
export function inrExact(paise: number | null | undefined): string {
  const value = rupees(paise);
  return `${value < 0 ? "-" : ""}₹${Math.abs(value).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function pct(value: number | null | undefined, digits = 1): string {
  return `${(Number(value || 0) * 100).toFixed(digits)}%`;
}

export function num(value: number | null | undefined): string {
  return Number(value || 0).toLocaleString("en-IN");
}

export function signedPct(value: number | null | undefined, digits = 1): string {
  const v = Number(value || 0);
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

/**
 * The world model records everything in UTC. A timestamp that arrives without
 * an offset is still UTC, so pin it rather than letting the browser read it as
 * local time — otherwise every "x ago" is wrong by the viewer's UTC offset.
 */
export function parseInstant(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  const text = String(value);
  // A calendar day is a label, not an instant: build it locally so the bucket
  // never renders as the previous day west of Greenwich.
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (day) return new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]));
  const bare = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(text);
  const date = new Date(bare ? `${text.replace(" ", "T")}Z` : text);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Clock time for an instant, used as an x-axis label on intraday series. */
export function timeOfDay(value: string | Date | null | undefined): string {
  const d = parseInstant(value);
  if (!d) return "—";
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

export function shortDate(value: string | Date | null | undefined): string {
  const d = parseInstant(value);
  if (!d) return value ? String(value) : "—";
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

export function dateTime(value: string | Date | null | undefined): string {
  const d = parseInstant(value);
  if (!d) return value ? String(value) : "—";
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(value: string | Date | null | undefined): string {
  const d = parseInstant(value);
  if (!d) return value ? String(value) : "—";
  const diff = Date.now() - d.getTime();
  const mins = Math.abs(Math.round(diff / 60000));
  // Scheduled payouts and payroll are legitimately in the future - read them forwards.
  const phrase = (amount: number, unit: string) => (diff >= 0 ? `${amount}${unit} ago` : `in ${amount}${unit}`);
  if (mins < 1) return "just now";
  if (mins < 60) return phrase(mins, "m");
  const hours = Math.round(mins / 60);
  if (hours < 24) return phrase(hours, "h");
  return phrase(Math.round(hours / 24), "d");
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .replace(/[_.]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export type Tone = "good" | "warning" | "serious" | "critical" | "neutral" | "brand";

/** Maps a domain word onto the reserved status palette. */
export function toneFor(value: string | null | undefined): Tone {
  const key = String(value || "").toLowerCase();
  if (["healthy", "low", "verified", "approved", "processed", "paid", "captured", "positive", "completed", "passed", "resolved", "good", "active"].includes(key))
    return "good";
  if (["stable", "medium", "watch", "pending", "open", "scheduled", "authorized", "draft", "generated", "viewed", "running"].includes(key))
    return "warning";
  if (["high", "delayed", "overdue", "serious", "skipped"].includes(key)) return "serious";
  if (["critical", "failed", "rejected", "cancelled", "errored", "expired", "tripped", "negative"].includes(key))
    return "critical";
  return "neutral";
}

export const TONE_GLYPH: Record<Tone, string> = {
  good: "●",
  warning: "▲",
  serious: "◆",
  critical: "■",
  neutral: "○",
  brand: "●",
};

export function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}
