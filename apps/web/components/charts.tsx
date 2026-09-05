"use client";

/**
 * A small SVG chart kit built on the project's validated palette.
 *
 * Rules held here so every chart obeys them by construction:
 *  - one y axis, never two;
 *  - categorical colour is assigned by fixed slot order (SERIES below) and
 *    follows the entity, so filtering never repaints the survivors;
 *  - >= 2 series always render a legend, and every chart ships a table view so
 *    no value is reachable only by hovering;
 *  - hairline solid grid, thin marks, 2px gaps between adjacent fills.
 */

import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

export const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)", "var(--s8)"];
export const SEQ = ["var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)", "var(--seq-6)"];

export type Serie = { key: string; label: string; color?: string };

/* -------------------------------------------------------------- plumbing -- */

/**
 * Measures the holder with a callback ref rather than an effect: a chart whose
 * data arrives late mounts its holder after the first render, and an effect with
 * an empty dep list would never see that node.
 */
function useWidth<T extends HTMLElement>() {
  const [width, setWidth] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);

  const ref = useCallback((node: T | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!node) return;
    const measure = () => setWidth(node.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const next = new ResizeObserver(measure);
    next.observe(node);
    observer.current = next;
  }, []);

  useEffect(() => () => observer.current?.disconnect(), []);
  return { ref, width };
}

type TipState = { x: number; y: number; node: ReactNode } | null;

function Tip({ tip, width }: { tip: TipState; width: number }) {
  if (!tip) return null;
  const flip = tip.x > width - 170;
  return (
    <div
      className="chart-tip"
      style={{
        left: tip.x,
        top: tip.y,
        transform: `translate(${flip ? "calc(-100% - 12px)" : "12px"}, -50%)`,
      }}
    >
      {tip.node}
    </div>
  );
}

/** Ticks from 0 to a round number at or above `max`, so no mark can escape the plot. */
function niceTicks(max: number, count = 4): number[] {
  if (!Number.isFinite(max) || max <= 0) return [0, 1];
  const raw = max / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? magnitude * 10;
  const top = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let i = 0; i * step <= top + step * 1e-6; i += 1) ticks.push(i * step);
  return ticks.length > 1 ? ticks : [0, top || 1];
}

/* ----------------------------------------------------------------- frame -- */

export function ChartFrame({
  title,
  subtitle,
  actions,
  legend,
  table,
  children,
  stale,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  legend?: Serie[];
  table: { columns: string[]; rows: ReactNode[][] };
  children: ReactNode;
  stale?: boolean;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <section className="card">
      <header className="card-head">
        <div>
          <div className="card-title">{title}</div>
          {subtitle && <div className="card-sub">{subtitle}</div>}
        </div>
        <div className="row tight">
          {actions}
          <div className="segmented">
            <button type="button" aria-pressed={view === "chart"} onClick={() => setView("chart")}>
              Chart
            </button>
            <button type="button" aria-pressed={view === "table"} onClick={() => setView("table")}>
              Table
            </button>
          </div>
        </div>
      </header>
      {legend && legend.length > 1 && (
        <div className="chart-legend" style={{ marginBottom: 10 }}>
          {legend.map((serie, index) => (
            <span className="key" key={serie.key}>
              <i style={{ background: serie.color || SERIES[index % SERIES.length] }} />
              {serie.label}
            </span>
          ))}
        </div>
      )}
      <div className={stale ? "stale" : undefined}>
        {view === "chart" ? (
          children
        ) : (
          <div className="table-wrap" style={{ maxHeight: 340 }}>
            <table className="data">
              <thead>
                <tr>
                  {table.columns.map((column, index) => (
                    <th key={column} className={index === 0 ? undefined : "right"}>
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, cellIndex) => (
                      <td key={cellIndex} className={cellIndex === 0 ? undefined : "right"}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ line chart -- */

export function LineChart({
  points,
  series,
  xKey = "x",
  height = 230,
  format = (v: number) => String(v),
  xFormat = (v: string) => v,
  area = false,
}: {
  points: Record<string, any>[];
  series: Serie[];
  xKey?: string;
  height?: number;
  format?: (value: number) => string;
  xFormat?: (value: string) => string;
  area?: boolean;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState>(null);
  const [hover, setHover] = useState<number | null>(null);

  const pad = { top: 12, right: 18, bottom: 26, left: 58 };
  const plotW = Math.max(10, width - pad.left - pad.right);
  const plotH = height - pad.top - pad.bottom;

  /** null/undefined means "no observation", which is not the same as zero. */
  const at = (point: Record<string, any>, key: string): number | null => {
    const raw = point?.[key];
    if (raw === null || raw === undefined || raw === "") return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  };

  const values = points.flatMap((point) => series.map((serie) => at(point, serie.key) ?? 0));
  const rawMax = Math.max(...values, 0);
  const ticks = niceTicks(rawMax || 1);
  const yMax = ticks[ticks.length - 1] || 1;
  const stepX = points.length > 1 ? plotW / (points.length - 1) : 0;

  const xAt = (index: number) => pad.left + (points.length > 1 ? index * stepX : plotW / 2);
  const yAt = (value: number) => pad.top + plotH - (Math.max(0, value) / yMax) * plotH;

  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(3, Math.floor(plotW / 78))));

  const onMove = useCallback(
    (event: React.MouseEvent<SVGSVGElement>) => {
      if (!points.length) return;
      const box = event.currentTarget.getBoundingClientRect();
      const x = event.clientX - box.left;
      const index = Math.max(0, Math.min(points.length - 1, Math.round((x - pad.left) / (stepX || 1))));
      setHover(index);
      setTip({
        x: xAt(index),
        y: height / 2,
        node: (
          <>
            <div className="t-head">{xFormat(String(points[index][xKey]))}</div>
            {series.map((serie, sIndex) => (
              <div className="t-row" key={serie.key}>
                <span>
                  <i style={{ background: serie.color || SERIES[sIndex % SERIES.length] }} />
                  {serie.label}
                </span>
                <strong>
                  {at(points[index], serie.key) === null ? "no data" : format(at(points[index], serie.key) as number)}
                </strong>
              </div>
            ))}
          </>
        ),
      });
    },
    [points, series, stepX, xKey, xFormat, format, height],
  );

  return (
    <div className="chart-holder" ref={ref} style={{ height }}>
      {!points.length || width === 0 ? (
        <div className="empty" style={{ height }}>
          {points.length ? "" : "No data in this range."}
        </div>
      ) : (
      <svg
        width={width}
        height={height}
        onMouseMove={onMove}
        onMouseLeave={() => {
          setTip(null);
          setHover(null);
        }}
        role="img"
        aria-label={`Line chart: ${series.map((s) => s.label).join(", ")}`}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={pad.left} x2={pad.left + plotW} y1={yAt(tick)} y2={yAt(tick)} stroke="var(--grid)" strokeWidth={1} />
            <text className="axis-text" x={pad.left - 8} y={yAt(tick) + 3.5} textAnchor="end">
              {format(tick)}
            </text>
          </g>
        ))}
        <line
          x1={pad.left}
          x2={pad.left + plotW}
          y1={pad.top + plotH}
          y2={pad.top + plotH}
          stroke="var(--axis)"
          strokeWidth={1}
        />
        {points.map((point, index) =>
          index % labelEvery === 0 || index === points.length - 1 ? (
            <text key={index} className="axis-text" x={xAt(index)} y={height - 8} textAnchor="middle">
              {xFormat(String(point[xKey]))}
            </text>
          ) : null,
        )}

        {series.map((serie, sIndex) => {
          const color = serie.color || SERIES[sIndex % SERIES.length];
          // Break the line wherever there is no observation rather than dropping to zero.
          let started = false;
          const path = points
            .map((point, index) => {
              const value = at(point, serie.key);
              if (value === null) {
                started = false;
                return "";
              }
              const command = started ? "L" : "M";
              started = true;
              return `${command}${xAt(index)},${yAt(value)}`;
            })
            .filter(Boolean)
            .join(" ");
          const observed = points
            .map((point, index) => ({ index, value: at(point, serie.key) }))
            .filter((p) => p.value !== null) as { index: number; value: number }[];
          return (
            <g key={serie.key}>
              {area && series.length === 1 && observed.length > 1 && (
                <path
                  d={`${path} L${xAt(observed[observed.length - 1].index)},${pad.top + plotH} L${xAt(observed[0].index)},${pad.top + plotH} Z`}
                  fill={color}
                  opacity={0.13}
                />
              )}
              <path d={path} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
              {/* an isolated observation would otherwise draw nothing */}
              {observed.length === 1 && <circle cx={xAt(observed[0].index)} cy={yAt(observed[0].value)} r={3} fill={color} />}
            </g>
          );
        })}

        {hover !== null && (
          <g>
            <line
              x1={xAt(hover)}
              x2={xAt(hover)}
              y1={pad.top}
              y2={pad.top + plotH}
              stroke="var(--line-strong)"
              strokeWidth={1}
            />
            {series.map((serie, sIndex) => {
              const value = at(points[hover], serie.key);
              if (value === null) return null;
              return (
                <circle
                  key={serie.key}
                  cx={xAt(hover)}
                  cy={yAt(value)}
                  r={4.5}
                  fill={serie.color || SERIES[sIndex % SERIES.length]}
                  stroke="var(--surface)"
                  strokeWidth={2}
                />
              );
            })}
          </g>
        )}

        {/* Selective direct label: the endpoint of each series, never every point. */}
        {series.length <= 3 &&
          series.map((serie, sIndex) => {
            const lastObserved = [...points].reverse().find((point) => at(point, serie.key) !== null);
            if (!lastObserved) return null;
            const last = at(lastObserved, serie.key) as number;
            // keep the label inside the plot band so it can never sit over the card header
            const y = Math.min(pad.top + plotH - 2, Math.max(pad.top + 10, yAt(last) - 8));
            return (
              <text
                key={`label-${serie.key}`}
                className="label-text"
                x={xAt(points.length - 1)}
                y={y}
                textAnchor="end"
                fill={serie.color || SERIES[sIndex % SERIES.length]}
                style={{ fontWeight: 600 }}
              >
                {format(last)}
              </text>
            );
          })}
      </svg>
      )}
      <Tip tip={tip} width={width} />
    </div>
  );
}

/* --------------------------------------------------- stacked column chart -- */

export function StackedBars({
  points,
  series,
  xKey = "x",
  height = 230,
  format = (v: number) => String(v),
  xFormat = (v: string) => v,
}: {
  points: Record<string, any>[];
  series: Serie[];
  xKey?: string;
  height?: number;
  format?: (value: number) => string;
  xFormat?: (value: string) => string;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState>(null);

  const pad = { top: 12, right: 14, bottom: 26, left: 58 };
  const plotW = Math.max(10, width - pad.left - pad.right);
  const plotH = height - pad.top - pad.bottom;
  const totals = points.map((point) => series.reduce((sum, serie) => sum + (Number(point[serie.key]) || 0), 0));
  const ticks = niceTicks(Math.max(...totals, 1));
  const yMax = ticks[ticks.length - 1] || 1;
  const slot = plotW / Math.max(points.length, 1);
  const barW = Math.max(3, Math.min(30, slot - 4));
  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(3, Math.floor(plotW / 78))));

  return (
    <div className="chart-holder" ref={ref} style={{ height }}>
      {!points.length || width === 0 ? (
        <div className="empty" style={{ height }}>
          {points.length ? "" : "No data in this range."}
        </div>
      ) : (
      <svg width={width} height={height} role="img" aria-label={`Stacked bars: ${series.map((s) => s.label).join(", ")}`}>
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={pad.left}
              x2={pad.left + plotW}
              y1={pad.top + plotH - (tick / yMax) * plotH}
              y2={pad.top + plotH - (tick / yMax) * plotH}
              stroke="var(--grid)"
              strokeWidth={1}
            />
            <text className="axis-text" x={pad.left - 8} y={pad.top + plotH - (tick / yMax) * plotH + 3.5} textAnchor="end">
              {format(tick)}
            </text>
          </g>
        ))}
        <line x1={pad.left} x2={pad.left + plotW} y1={pad.top + plotH} y2={pad.top + plotH} stroke="var(--axis)" />

        {points.map((point, index) => {
          const cx = pad.left + slot * index + slot / 2;
          let cursor = pad.top + plotH;
          return (
            <g
              key={index}
              onMouseEnter={() =>
                setTip({
                  x: cx,
                  y: height / 2,
                  node: (
                    <>
                      <div className="t-head">{xFormat(String(point[xKey]))}</div>
                      {series.map((serie, sIndex) => (
                        <div className="t-row" key={serie.key}>
                          <span>
                            <i style={{ background: serie.color || SERIES[sIndex % SERIES.length] }} />
                            {serie.label}
                          </span>
                          <strong>{format(Number(point[serie.key]) || 0)}</strong>
                        </div>
                      ))}
                    </>
                  ),
                })
              }
              onMouseLeave={() => setTip(null)}
            >
              {/* generous hit target, larger than the mark */}
              <rect x={cx - slot / 2} y={pad.top} width={slot} height={plotH} fill="transparent" />
              {series.map((serie, sIndex) => {
                const value = Number(point[serie.key]) || 0;
                const h = (value / yMax) * plotH;
                if (h <= 0) return null;
                const y = cursor - h;
                cursor = y - 2; /* 2px surface gap between stacked segments */
                return (
                  <rect
                    key={serie.key}
                    x={cx - barW / 2}
                    y={y}
                    width={barW}
                    height={Math.max(1, h)}
                    rx={sIndex === series.length - 1 ? 3 : 0}
                    fill={serie.color || SERIES[sIndex % SERIES.length]}
                  />
                );
              })}
            </g>
          );
        })}

        {points.map((point, index) =>
          index % labelEvery === 0 || index === points.length - 1 ? (
            <text
              key={`x-${index}`}
              className="axis-text"
              x={pad.left + slot * index + slot / 2}
              y={height - 8}
              textAnchor="middle"
            >
              {xFormat(String(point[xKey]))}
            </text>
          ) : null,
        )}
      </svg>
      )}
      <Tip tip={tip} width={width} />
    </div>
  );
}

/* ---------------------------------------------------- horizontal bar list -- */

export function BarList({
  items,
  format = (v: number) => String(v),
  color = SERIES[0],
  ordinal = false,
  meta,
  maxRows = 12,
}: {
  items: { key: string; label: string; value: number }[];
  format?: (value: number) => string;
  color?: string;
  /** Ordered categories (funnel stages, tiers) use the single-hue ordinal ramp. */
  ordinal?: boolean;
  meta?: (item: { key: string; label: string; value: number }, index: number) => ReactNode;
  maxRows?: number;
}) {
  const rows = items.slice(0, maxRows);
  const max = Math.max(...rows.map((row) => Math.abs(row.value)), 1);
  if (!rows.length) return <div className="empty">Nothing to show.</div>;
  return (
    <div className="stack-v">
      {rows.map((item, index) => (
        <div key={item.key} style={{ display: "grid", gap: 5 }}>
          <div className="spread" style={{ fontSize: 12.5 }}>
            <span>{item.label}</span>
            <span className="row tight">
              {meta?.(item, index)}
              <strong className="num">{format(item.value)}</strong>
            </span>
          </div>
          <div style={{ height: 8, background: "var(--surface-3)", borderRadius: 4, overflow: "hidden" }}>
            <div
              style={{
                width: `${(Math.abs(item.value) / max) * 100}%`,
                height: "100%",
                borderRadius: 4,
                background: ordinal ? SEQ[Math.min(index, SEQ.length - 1)] : color,
                minWidth: item.value ? 3 : 0,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ----------------------------------------------------------------- donut -- */

export function Donut({
  slices,
  format = (v: number) => String(v),
  size = 180,
}: {
  slices: { key: string; label: string; value: number }[];
  format?: (value: number) => string;
  size?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const visible = slices.filter((slice) => slice.value > 0).slice(0, 6);
  const total = visible.reduce((sum, slice) => sum + slice.value, 0);
  if (!total) return <div className="empty">Nothing outstanding.</div>;

  const radius = size / 2 - 6;
  const inner = radius * 0.62;
  let angle = -Math.PI / 2;
  const arcs = visible.map((slice, index) => {
    const sweep = (slice.value / total) * Math.PI * 2;
    // 2px surface gap between adjacent fills, expressed as an angular inset
    const gap = Math.min(0.03, sweep / 6);
    const start = angle + gap / 2;
    const end = angle + sweep - gap / 2;
    angle += sweep;
    const large = end - start > Math.PI ? 1 : 0;
    const cx = size / 2;
    const cy = size / 2;
    const d = [
      `M${cx + Math.cos(start) * radius},${cy + Math.sin(start) * radius}`,
      `A${radius},${radius} 0 ${large} 1 ${cx + Math.cos(end) * radius},${cy + Math.sin(end) * radius}`,
      `L${cx + Math.cos(end) * inner},${cy + Math.sin(end) * inner}`,
      `A${inner},${inner} 0 ${large} 0 ${cx + Math.cos(start) * inner},${cy + Math.sin(start) * inner}`,
      "Z",
    ].join(" ");
    return { d, slice, index };
  });

  const focus = hover === null ? null : visible[hover];

  return (
    <div className="row" style={{ gap: 18, alignItems: "center" }}>
      <svg width={size} height={size} role="img" aria-label="Composition">
        {arcs.map(({ d, index }) => (
          <path
            key={index}
            d={d}
            fill={SERIES[index % SERIES.length]}
            opacity={hover === null || hover === index ? 1 : 0.35}
            onMouseEnter={() => setHover(index)}
            onMouseLeave={() => setHover(null)}
          />
        ))}
        <text x={size / 2} y={size / 2 - 4} textAnchor="middle" style={{ fill: "var(--ink)", fontSize: 15, fontWeight: 600 }}>
          {format(focus ? focus.value : total)}
        </text>
        <text x={size / 2} y={size / 2 + 14} textAnchor="middle" className="axis-text">
          {focus ? focus.label : "Total"}
        </text>
      </svg>
      <div className="stack-v" style={{ flex: 1, minWidth: 160, gap: 6 }}>
        {visible.map((slice, index) => (
          <div
            key={slice.key}
            className="spread"
            style={{ fontSize: 12.5, opacity: hover === null || hover === index ? 1 : 0.5 }}
            onMouseEnter={() => setHover(index)}
            onMouseLeave={() => setHover(null)}
          >
            <span className="row tight">
              <i
                style={{
                  width: 9,
                  height: 9,
                  borderRadius: 2.5,
                  background: SERIES[index % SERIES.length],
                  display: "inline-block",
                }}
              />
              {slice.label}
            </span>
            <span className="num">
              <strong>{format(slice.value)}</strong>{" "}
              <span className="tiny">{((slice.value / total) * 100).toFixed(0)}%</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- scatter -- */

export function Scatter({
  points,
  height = 230,
  format = (v: number) => String(v),
  xLabel,
  yLabel,
}: {
  points: { x: number; y: number; label: string; tone?: string }[];
  height?: number;
  format?: (value: number) => string;
  xLabel: string;
  yLabel: string;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState>(null);
  const pad = { top: 14, right: 16, bottom: 34, left: 62 };
  const plotW = Math.max(10, width - pad.left - pad.right);
  const plotH = height - pad.top - pad.bottom;
  const max = Math.max(...points.flatMap((p) => [p.x, p.y]), 1);
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const xAt = (v: number) => pad.left + (v / top) * plotW;
  const yAt = (v: number) => pad.top + plotH - (v / top) * plotH;

  return (
    <div className="chart-holder" ref={ref} style={{ height }}>
      {!points.length || width === 0 ? (
        <div className="empty" style={{ height }}>
          {points.length ? "" : "No outcomes recorded yet."}
        </div>
      ) : (
      <svg width={width} height={height} role="img" aria-label={`${yLabel} against ${xLabel}`}>
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={pad.left} x2={pad.left + plotW} y1={yAt(tick)} y2={yAt(tick)} stroke="var(--grid)" />
            <text className="axis-text" x={pad.left - 8} y={yAt(tick) + 3.5} textAnchor="end">
              {format(tick)}
            </text>
            <text className="axis-text" x={xAt(tick)} y={height - 16} textAnchor="middle">
              {format(tick)}
            </text>
          </g>
        ))}
        {/* perfect-calibration reference */}
        <line
          x1={pad.left}
          y1={pad.top + plotH}
          x2={pad.left + plotW}
          y2={pad.top}
          stroke="var(--line-strong)"
          strokeWidth={1}
        />
        <text className="axis-text" x={pad.left + plotW} y={pad.top - 2} textAnchor="end">
          perfect calibration
        </text>
        <text className="axis-text" x={pad.left + plotW / 2} y={height - 2} textAnchor="middle">
          {xLabel}
        </text>
        {points.map((point, index) => (
          <circle
            key={index}
            cx={xAt(point.x)}
            cy={yAt(point.y)}
            r={6}
            fill={point.tone || SERIES[0]}
            stroke="var(--surface)"
            strokeWidth={2}
            onMouseEnter={() =>
              setTip({
                x: xAt(point.x),
                y: yAt(point.y),
                node: (
                  <>
                    <div className="t-head">{point.label}</div>
                    <div className="t-row">
                      <span>{xLabel}</span>
                      <strong>{format(point.x)}</strong>
                    </div>
                    <div className="t-row">
                      <span>{yLabel}</span>
                      <strong>{format(point.y)}</strong>
                    </div>
                  </>
                ),
              })
            }
            onMouseLeave={() => setTip(null)}
          />
        ))}
      </svg>
      )}
      <Tip tip={tip} width={width} />
    </div>
  );
}

/* ------------------------------------------------------------- sparkline -- */

export function Sparkline({
  values,
  color = SERIES[0],
  height = 34,
}: {
  values: number[];
  color?: string;
  height?: number;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  if (values.length < 2 || width === 0) return <div ref={ref} style={{ width: "100%", height }} />;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  const path = values
    .map((value, index) => `${index ? "L" : "M"}${index * step},${height - 3 - ((value - min) / span) * (height - 8)}`)
    .join(" ");
  return (
    <div ref={ref} style={{ width: "100%", height }}>
      <svg width={width} height={height} aria-hidden="true">
        <path d={`${path} L${width},${height} L0,${height} Z`} fill={color} opacity={0.12} />
        <path d={path} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    </div>
  );
}

/* ---------------------------------------------------------- forecast band -- */

export function BandChart({
  points,
  height = 230,
  format = (v: number) => String(v),
}: {
  points: { label: string; p10: number; p50: number; p90: number }[];
  height?: number;
  format?: (value: number) => string;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState>(null);
  const pad = { top: 14, right: 18, bottom: 26, left: 62 };
  const plotW = Math.max(10, width - pad.left - pad.right);
  const plotH = height - pad.top - pad.bottom;
  const ticks = niceTicks(Math.max(...points.map((p) => p.p90), 1));
  const yMax = ticks[ticks.length - 1] || 1;
  const stepX = points.length > 1 ? plotW / (points.length - 1) : 0;
  const xAt = (index: number) => pad.left + (points.length > 1 ? index * stepX : plotW / 2);
  const yAt = (value: number) => pad.top + plotH - (Math.max(0, value) / yMax) * plotH;

  const bandPath = [
    ...points.map((point, index) => `${index ? "L" : "M"}${xAt(index)},${yAt(point.p90)}`),
    ...[...points].reverse().map((point, index) => `L${xAt(points.length - 1 - index)},${yAt(point.p10)}`),
    "Z",
  ].join(" ");

  return (
    <div className="chart-holder" ref={ref} style={{ height }}>
      {!points.length || width === 0 ? (
        <div className="empty" style={{ height }}>
          {points.length ? "" : "No forecast yet."}
        </div>
      ) : (
      <svg width={width} height={height} role="img" aria-label="Forecast with p10-p90 band">
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={pad.left} x2={pad.left + plotW} y1={yAt(tick)} y2={yAt(tick)} stroke="var(--grid)" />
            <text className="axis-text" x={pad.left - 8} y={yAt(tick) + 3.5} textAnchor="end">
              {format(tick)}
            </text>
          </g>
        ))}
        <path d={bandPath} fill={SERIES[0]} opacity={0.16} />
        <path
          d={points.map((point, index) => `${index ? "L" : "M"}${xAt(index)},${yAt(point.p50)}`).join(" ")}
          fill="none"
          stroke={SERIES[0]}
          strokeWidth={2}
        />
        {points.map((point, index) => (
          <g key={point.label}>
            <circle
              cx={xAt(index)}
              cy={yAt(point.p50)}
              r={5}
              fill={SERIES[0]}
              stroke="var(--surface)"
              strokeWidth={2}
              onMouseEnter={() =>
                setTip({
                  x: xAt(index),
                  y: yAt(point.p50),
                  node: (
                    <>
                      <div className="t-head">{point.label}</div>
                      <div className="t-row">
                        <span>p90</span>
                        <strong>{format(point.p90)}</strong>
                      </div>
                      <div className="t-row">
                        <span>p50</span>
                        <strong>{format(point.p50)}</strong>
                      </div>
                      <div className="t-row">
                        <span>p10</span>
                        <strong>{format(point.p10)}</strong>
                      </div>
                    </>
                  ),
                })
              }
              onMouseLeave={() => setTip(null)}
            />
            <text className="axis-text" x={xAt(index)} y={height - 8} textAnchor="middle">
              {point.label}
            </text>
          </g>
        ))}
      </svg>
      )}
      <Tip tip={tip} width={width} />
    </div>
  );
}
