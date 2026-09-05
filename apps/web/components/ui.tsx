"use client";

import { ReactNode, useEffect, useState } from "react";
import { TONE_GLYPH, Tone, dateTime, titleCase, toneFor } from "@/lib/format";

/* ------------------------------------------------------------------ card -- */

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = "",
  stale = false,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  stale?: boolean;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <div className="card-title">{title}</div>}
            {subtitle && <div className="card-sub">{subtitle}</div>}
          </div>
          {actions && <div className="row tight">{actions}</div>}
        </header>
      )}
      <div className={stale ? "stale" : undefined}>{children}</div>
    </section>
  );
}

/* ----------------------------------------------------------------- badge -- */

export function Badge({
  children,
  tone = "neutral",
  glyph = true,
}: {
  children: ReactNode;
  tone?: Tone;
  glyph?: boolean;
}) {
  return (
    <span className={`badge ${tone}`}>
      {glyph && tone !== "neutral" && <span className="glyph" aria-hidden="true">{TONE_GLYPH[tone]}</span>}
      {children}
    </span>
  );
}

/** Badge whose tone is derived from a domain status word. Icon + label, never colour alone. */
export function StatusBadge({ value }: { value: string | null | undefined }) {
  return <Badge tone={toneFor(value)}>{titleCase(value)}</Badge>;
}

/* ------------------------------------------------------------- stat tile -- */

export function Stat({
  label,
  value,
  foot,
  delta,
  chart,
  tone,
}: {
  label: string;
  value: ReactNode;
  foot?: ReactNode;
  delta?: { value: number; label?: string; goodWhenUp?: boolean };
  chart?: ReactNode;
  tone?: Tone;
}) {
  let deltaNode: ReactNode = null;
  if (delta && Number.isFinite(delta.value)) {
    const up = delta.value > 0.0005;
    const down = delta.value < -0.0005;
    const goodWhenUp = delta.goodWhenUp ?? true;
    const cls = !up && !down ? "flat" : (up ? goodWhenUp : !goodWhenUp) ? "up" : "down";
    deltaNode = (
      <span className={`delta ${cls}`}>
        <span aria-hidden="true">{up ? "▲" : down ? "▼" : "■"}</span>
        {`${delta.value > 0 ? "+" : ""}${(delta.value * 100).toFixed(1)}%`}
        {delta.label ? <span className="tiny">{delta.label}</span> : null}
      </span>
    );
  }
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={tone ? { color: `var(--${tone === "neutral" ? "ink" : tone})` } : undefined}>
        {value}
      </div>
      {(deltaNode || foot) && (
        <div className="stat-foot">
          {deltaNode}
          {foot}
        </div>
      )}
      {chart}
    </div>
  );
}

export function StatCard(props: Parameters<typeof Stat>[0]) {
  return (
    <div className="card">
      <Stat {...props} />
    </div>
  );
}

/* ------------------------------------------------------------------ misc -- */

export function Meter({ value, tone = "brand" }: { value: number; tone?: Tone }) {
  const pctValue = Math.max(0, Math.min(1, Number(value) || 0)) * 100;
  return (
    <div className="meter" role="img" aria-label={`${pctValue.toFixed(0)} percent`}>
      <i style={{ width: `${pctValue}%`, background: `var(--${tone === "neutral" ? "muted" : tone})` }} />
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="empty">
      <strong style={{ fontWeight: 550 }}>{title}</strong>
      {hint && <span className="tiny">{hint}</span>}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  if (!children) return null;
  return <p className="err">{children}</p>;
}

export function Skeleton({ height = 90 }: { height?: number }) {
  return <div className="skeleton" style={{ height }} />;
}

export function Json({ value, maxHeight }: { value: unknown; maxHeight?: number }) {
  return (
    <pre className="json" style={maxHeight ? { maxHeight } : undefined}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([key, value]) => (
        <div key={key} style={{ display: "contents" }}>
          <dt>{key}</dt>
          <dd>{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ------------------------------------------------------------------ tabs -- */

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string; count?: number }[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          className="tab"
          aria-selected={tab.id === active}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
          {tab.count !== undefined && <span className="tiny"> {tab.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  label?: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- drawer -- */

export function Drawer({
  open,
  title,
  subtitle,
  onClose,
  children,
}: {
  open: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : "Details"}>
        <header className="drawer-head">
          <div>
            <div className="card-title">{title}</div>
            {subtitle && <div className="card-sub">{subtitle}</div>}
          </div>
          <button className="iconbtn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </>
  );
}

/* ------------------------------------------------------------- data grid -- */

export type Column<T> = {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  align?: "left" | "right";
  width?: number;
};

export function DataTable<T extends Record<string, any>>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty = "Nothing here yet.",
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  onRowClick?: (row: T) => void;
  empty?: string;
}) {
  if (!rows.length) return <Empty title={empty} />;
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} className={column.align === "right" ? "right" : undefined} style={column.width ? { width: column.width } : undefined}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={rowKey(row, index)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              style={onRowClick ? { cursor: "pointer" } : undefined}
            >
              {columns.map((column) => (
                <td key={column.key} className={column.align === "right" ? "right" : undefined}>
                  {column.render ? column.render(row) : formatCell(row[column.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function formatCell(value: unknown): ReactNode {
  if (value === null || value === undefined || value === "") return <span className="tiny">—</span>;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return <span className="num">{value.toLocaleString("en-IN")}</span>;
  if (typeof value === "object") {
    return (
      <span className="cell-clip mono" title={JSON.stringify(value)}>
        {JSON.stringify(value)}
      </span>
    );
  }
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) return <span className="num">{dateTime(text)}</span>;
  if (text.length > 46) {
    return (
      <span className="cell-clip" title={text}>
        {text}
      </span>
    );
  }
  return text;
}

/* ----------------------------------------------------------- theme toggle -- */

const THEME_KEY = "bb_theme";

export function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("dark");

  useEffect(() => {
    const current = (document.documentElement.getAttribute("data-theme") as "light" | "dark") || "dark";
    setTheme(current);
  }, []);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem(THEME_KEY, next);
    setTheme(next);
  }

  return (
    <button className="btn ghost sm" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
      <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
