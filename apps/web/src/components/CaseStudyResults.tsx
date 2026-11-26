import { useState } from "react";
import { AnalysisDetail, type ExperimentResult } from "@/components/ExperimentResults";
import { DotWhisker, fmt, type Summary } from "@/components/SimulationResults";
import { OriginBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";

// --- iFogSim EEG case study -------------------------------------------------------------------------

type EEGRow = {
  headset: "A" | "B";
  placement: "cloud_only" | "edge_ward";
  config: number;
  gateways: number;
  smartphones: number;
  loop_delay_ms: Summary;
  loops_measured: number;
  network_usage_kb: Summary;
  power_w: Record<string, Summary>;
  energy_3h_mj: Record<string, number>;
  max_cpu_utilization: number;
  busiest_device: string;
  module_hosts: Record<string, string>;
  paper_loop_delay_ms: number | null;
  paper_network_usage_kb: number | null;
};

export type EEGResult = {
  kind: "simulation.case_study.ifogsim_eeg";
  data_origin: string;
  params: { configs: number[]; headsets: string[]; placements: string[]; replications: number; duration_s: number };
  paper: { citation: string; doi: string };
  sources: Record<string, string>;
  paper_values_note: string;
  rows: EEGRow[];
  checks: { claim: string; paper: string; holds: boolean; detail?: string }[];
};

const SERIES = [
  { headset: "A", placement: "edge_ward", label: "Headset A, edge-ward", color: "var(--st-implemented)", light: true },
  { headset: "B", placement: "edge_ward", label: "Headset B, edge-ward", color: "var(--st-implemented)", light: false },
  { headset: "A", placement: "cloud_only", label: "Headset A, cloud-only", color: "var(--accent)", light: true },
  { headset: "B", placement: "cloud_only", label: "Headset B, cloud-only", color: "var(--accent)", light: false },
] as const;

const placementLabel = (p: string) => (p === "edge_ward" ? "Edge-ward" : "Cloud-only");

export function EEGCaseStudyView({ result }: { result: EEGResult }) {
  const series = SERIES.filter((s) => result.params.headsets.includes(s.headset) && result.params.placements.includes(s.placement));
  const find = (h: string, p: string, c: number) => result.rows.find((r) => r.headset === h && r.placement === p && r.config === c);
  const diff = (ours: number | null, paper: number | null) =>
    ours === null || paper === null || paper === 0 ? "–" : `${ours >= paper ? "+" : "−"}${Math.abs((ours / paper - 1) * 100).toFixed(0)}%`;

  return (
    <section className="mt-10 space-y-10">
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-lg font-semibold">Reproduction of the iFogSim EEG game case study</h2>
          <OriginBadge origin={result.data_origin} />
        </div>
        <p className="mt-2 max-w-3xl text-sm text-ink-2">
          {result.paper.citation}{" "}
          <a className="text-accent hover:underline" href={`https://doi.org/${result.paper.doi}`} target="_blank" rel="noreferrer">
            doi:{result.paper.doi}
          </a>
          . Each simulated value is the mean of {result.params.replications} runs of {result.params.duration_s} simulated seconds.
        </p>
      </div>

      <div>
        <h3 className="font-semibold">Does this run reproduce the paper's findings?</h3>
        <ul className="mt-3 divide-y divide-line border-y border-line text-sm">
          {result.checks.map((c) => (
            <li key={c.claim} className="flex gap-3 py-2.5">
              <span className={cn("mt-0.5 w-28 shrink-0 text-xs font-medium", c.holds ? "text-[var(--st-implemented)]" : "text-danger")}>
                {c.holds ? "Reproduced" : "Not reproduced"}
              </span>
              <div>
                <p>{c.claim} <span className="text-ink-3">({c.paper})</span></p>
                {c.detail && <p className="mt-0.5 text-xs text-ink-3">{c.detail}</p>}
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="grid gap-10 xl:grid-cols-2">
        <GroupedBars
          title="Average delay of the control loop"
          subtitle="EEG → client → concentration calculator → client → display"
          unit="ms, logarithmic scale"
          log
          configs={result.params.configs}
          series={series.map((s) => ({
            ...s,
            values: result.params.configs.map((c) => {
              const r = find(s.headset, s.placement, c);
              return { ours: r?.loop_delay_ms.mean ?? null, paper: r?.paper_loop_delay_ms ?? null };
            }),
          }))}
        />
        <GroupedBars
          title="Network usage"
          subtitle="Data rate × delay product, as defined by iFogSim"
          unit="KB"
          configs={result.params.configs}
          series={series.map((s) => ({
            ...s,
            values: result.params.configs.map((c) => {
              const r = find(s.headset, s.placement, c);
              return { ours: r?.network_usage_kb.mean ?? null, paper: r?.paper_network_usage_kb ?? null };
            }),
          }))}
        />
      </div>
      <p className="-mt-6 max-w-3xl text-xs text-ink-3">
        Bars are this simulation; black ticks are the paper. {result.paper_values_note}
      </p>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[60rem] text-sm">
          <thead className="text-left text-ink-3">
            <tr className="border-b border-line align-bottom">
              <th className="py-2 pr-3 font-normal">Config</th>
              <th className="py-2 pr-3 font-normal">Headset, placement</th>
              <th className="py-2 pr-3 text-right font-normal">Loop delay<span className="block text-xs">ms</span></th>
              <th className="py-2 pr-3 text-right font-normal">Paper<span className="block text-xs">ms</span></th>
              <th className="py-2 pr-3 text-right font-normal">Network<span className="block text-xs">KB</span></th>
              <th className="py-2 pr-3 text-right font-normal">Paper<span className="block text-xs">KB</span></th>
              <th className="py-2 pr-3 text-right font-normal">Difference<span className="block text-xs">network</span></th>
              <th className="py-2 pr-3 text-right font-normal">Busiest CPU<span className="block text-xs">utilisation</span></th>
              <th className="py-2 font-normal">Concentration calculator runs on</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {result.rows.map((r) => (
              <tr key={`${r.config}-${r.headset}-${r.placement}`}>
                <td className="py-2 pr-3 whitespace-nowrap">
                  {r.config} <span className="text-xs text-ink-3">({r.gateways} gw, {r.smartphones} phones)</span>
                </td>
                <td className="py-2 pr-3 whitespace-nowrap">{r.headset}, {placementLabel(r.placement).toLowerCase()}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{r.loop_delay_ms.mean?.toFixed(1) ?? "–"}</td>
                <td className="py-2 pr-3 text-right tabular-nums text-ink-3">{r.paper_loop_delay_ms ?? "–"}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{r.network_usage_kb.mean?.toFixed(1) ?? "–"}</td>
                <td className="py-2 pr-3 text-right tabular-nums text-ink-3">{r.paper_network_usage_kb ?? "–"}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{diff(r.network_usage_kb.mean, r.paper_network_usage_kb)}</td>
                <td className="py-2 pr-3 text-right tabular-nums" title={r.busiest_device}>{(r.max_cpu_utilization * 100).toFixed(0)}%</td>
                <td className="py-2">{r.module_hosts.concentration_calculator}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details className="text-sm">
        <summary className="cursor-pointer text-ink-2">Where each parameter comes from</summary>
        <table className="mt-3 w-full max-w-4xl text-sm">
          <tbody className="divide-y divide-line">
            {Object.entries(result.sources).map(([what, src]) => (
              <tr key={what}>
                <td className="py-1.5 pr-4">{what}</td>
                <td className="py-1.5 text-ink-2">{src}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}

type BarSeries = { label: string; color: string; light: boolean; values: { ours: number | null; paper: number | null }[] };

function GroupedBars({ title, subtitle, unit, configs, series, log = false }: {
  title: string; subtitle: string; unit: string; configs: number[]; series: BarSeries[]; log?: boolean;
}) {
  const all = series.flatMap((s) => s.values.flatMap((v) => [v.ours, v.paper])).filter((v): v is number => v !== null && v > 0);
  const maxV = Math.max(1, ...all);
  const minV = log ? Math.max(1, Math.min(...all) / 1.5) : 0;
  const W = 600, H = 300, left = 52, bottom = 34, top = 8;
  const plotH = H - bottom - top;
  const y = (v: number) => {
    if (log) return top + plotH - ((Math.log10(Math.max(v, minV)) - Math.log10(minV)) / (Math.log10(maxV * 1.2) - Math.log10(minV))) * plotH;
    return top + plotH - (v / (maxV * 1.08)) * plotH;
  };
  const ticks = log
    ? [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000].filter((t) => t >= minV && t <= maxV * 1.2)
    : niceLinear(maxV * 1.08);
  const groupW = (W - left - 8) / configs.length;
  const barW = Math.min(22, (groupW - 16) / series.length);

  return (
    <figure>
      <figcaption>
        <span className="text-sm font-medium">{title}</span> <span className="text-sm text-ink-3">({unit})</span>
        <span className="block text-xs text-ink-3">{subtitle}</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full" role="img" aria-label={`${title}, simulated and published values per configuration`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={W - 8} y1={y(t)} y2={y(t)} stroke="var(--line)" />
            <text x={left - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--ink-3)">{t >= 1000 ? `${t / 1000}k` : t}</text>
          </g>
        ))}
        {configs.map((c, ci) => {
          const gx = left + ci * groupW + (groupW - barW * series.length) / 2;
          return (
            <g key={c}>
              <text x={left + ci * groupW + groupW / 2} y={H - 12} textAnchor="middle" fontSize={12} fill="var(--ink-2)">Config {c}</text>
              {series.map((s, si) => {
                const v = s.values[ci];
                const x = gx + si * barW;
                return (
                  <g key={s.label}>
                    {v.ours !== null && (
                      <rect x={x + 1} y={y(v.ours)} width={barW - 2} height={Math.max(0, top + plotH - y(v.ours))}
                        fill={s.color} fillOpacity={s.light ? 0.45 : 1} rx={1.5}>
                        <title>{`${s.label}, Config ${c}: ${fmt(v.ours)} (paper ${v.paper ?? "not readable"})`}</title>
                      </rect>
                    )}
                    {v.paper !== null && v.paper > 0 && (
                      <line x1={x - 1} x2={x + barW + 1} y1={y(v.paper)} y2={y(v.paper)} stroke="var(--ink)" strokeWidth={2.5} />
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
        <line x1={left} x2={W - 8} y1={top + plotH} y2={top + plotH} stroke="var(--ink-3)" />
      </svg>
      <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
        {series.map((s) => (
          <li key={s.label} className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-3.5 rounded-sm" style={{ background: s.color, opacity: s.light ? 0.45 : 1 }} />
            {s.label}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-3.5 bg-ink" />
          Paper
        </li>
      </ul>
    </figure>
  );
}

function niceLinear(max: number): number[] {
  const raw = max / 5;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => s >= raw) ?? mag * 10;
  const out = [];
  for (let t = 0; t <= max + 1e-9; t += step) out.push(Number(t.toPrecision(10)));
  return out;
}

// --- DAG scheduling --------------------------------------------------------------------------------

type ScheduleMetrics = { makespan: number; slr: number; speedup: number; efficiency: number };

export type DagScheduleResult = {
  kind: "scheduler.dag_schedule";
  data_origin: string;
  workflow: { name: string; tasks: number; edges: number; processors: string[] };
  reference: string;
  schedule: { algorithm: string; metrics: ScheduleMetrics; slots: { task: string; processor: string; start: number; finish: number }[] };
  ranks: Record<string, number>;
  for_comparison: Record<string, ScheduleMetrics>;
  note: string | null;
};

const ALG_LABEL: Record<string, string> = { heft: "HEFT", cpop: "CPOP", random: "Random" };

export function DagScheduleView({ result }: { result: DagScheduleResult }) {
  const s = result.schedule;
  const rows = [[s.algorithm, s.metrics] as const, ...Object.entries(result.for_comparison)];
  return (
    <section className="mt-10 space-y-8">
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-lg font-semibold">{ALG_LABEL[s.algorithm]} schedule</h2>
          <OriginBadge origin={result.data_origin} />
        </div>
        <p className="mt-1 text-sm text-ink-2">
          {result.workflow.name}: {result.workflow.tasks} tasks, {result.workflow.edges} dependencies,{" "}
          {result.workflow.processors.length} processors. {result.note}
        </p>
      </div>
      <Gantt slots={s.slots} processors={result.workflow.processors} makespan={s.metrics.makespan} />
      <table className="w-full max-w-2xl text-sm">
        <thead className="text-left text-ink-3">
          <tr className="border-b border-line">
            <th className="py-2 pr-4 font-normal">Scheduler, same graph</th>
            <th className="py-2 pr-4 text-right font-normal">Makespan</th>
            <th className="py-2 pr-4 text-right font-normal">SLR</th>
            <th className="py-2 pr-4 text-right font-normal">Speedup</th>
            <th className="py-2 text-right font-normal">Efficiency</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map(([alg, m], i) => (
            <tr key={alg} className={i === 0 ? "font-medium" : ""}>
              <td className="py-2 pr-4">{ALG_LABEL[alg] ?? alg}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmt(m.makespan)}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmt(m.slr)}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{fmt(m.speedup)}</td>
              <td className="py-2 text-right tabular-nums">{fmt(m.efficiency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="max-w-3xl text-xs text-ink-3">
        SLR divides the makespan by the shortest possible critical path, so 1.0 is the lower bound. One graph is an
        illustration, not evidence: use “Experiment: compare DAG schedulers” to test many graphs. Reference: {result.reference}
      </p>
    </section>
  );
}

function Gantt({ slots, processors, makespan }: { slots: DagScheduleResult["schedule"]["slots"]; processors: string[]; makespan: number }) {
  const W = 900, left = 44, rowH = 34, top = 6;
  const H = top + processors.length * rowH + 26;
  const x = (t: number) => left + (t / (makespan || 1)) * (W - left - 10);
  const ticks = niceLinear(makespan);
  const many = slots.length > 60;
  return (
    <figure className="overflow-x-auto">
      <figcaption className="text-sm font-medium">Timeline per processor</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full min-w-[40rem]" role="img" aria-label="Gantt chart of the schedule">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={top} y2={top + processors.length * rowH} stroke="var(--line)" />
            <text x={x(t)} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--ink-3)">{t}</text>
          </g>
        ))}
        {processors.map((p, i) => (
          <text key={p} x={left - 8} y={top + i * rowH + rowH / 2 + 4} textAnchor="end" fontSize={12} fill="var(--ink-2)">{p}</text>
        ))}
        {slots.map((s) => {
          const row = processors.indexOf(s.processor);
          const w = x(s.finish) - x(s.start);
          return (
            <g key={s.task}>
              <rect x={x(s.start)} y={top + row * rowH + 4} width={Math.max(1, w - 1)} height={rowH - 8} rx={3}
                fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth={1} />
              {!many && w > 22 && (
                <text x={x(s.start) + w / 2} y={top + row * rowH + rowH / 2 + 4} textAnchor="middle" fontSize={11} fill="var(--ink)">{s.task}</text>
              )}
              <title>{`${s.task} on ${s.processor}: ${fmt(s.start)} to ${fmt(s.finish)}`}</title>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

export type DagComparisonResult = {
  kind: "simulation.dag_comparison";
  data_origin: string;
  params: { algorithms: string[]; graphs: number; tasks: number; processors: number; ccr: number; beta: number };
  reference: string;
  metric_info: Record<string, [string, "lower" | "higher", string]>;
  summary: Record<string, Record<string, Summary>>;
  tests: Record<string, ExperimentResult["analysis"][string]>;
};

export function DagComparisonView({ result }: { result: DagComparisonResult }) {
  const [open, setOpen] = useState<string | null>("slr");
  const algs = result.params.algorithms;
  const metrics = Object.keys(result.metric_info);
  return (
    <section className="mt-10 space-y-8">
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-lg font-semibold">DAG scheduler comparison</h2>
          <OriginBadge origin={result.data_origin} />
        </div>
        <p className="mt-1 max-w-3xl text-sm text-ink-2">
          {result.params.graphs} random graphs of {result.params.tasks} tasks on {result.params.processors} processors
          (CCR {result.params.ccr}, heterogeneity {result.params.beta}); every scheduler saw the same graphs. Means with
          95% confidence intervals; Friedman test with Holm-corrected Wilcoxon pairs. Generator and metrics follow{" "}
          {result.reference}
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] text-sm">
          <thead className="text-left text-ink-3">
            <tr className="border-b border-line align-bottom">
              <th className="py-2 pr-4 font-normal">Metric</th>
              {algs.map((a) => <th key={a} className="py-2 pr-4 text-right font-normal">{ALG_LABEL[a] ?? a}</th>)}
              <th className="py-2 text-right font-normal">Test</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {metrics.map((m) => {
              const [label, better, desc] = result.metric_info[m];
              const an = result.tests[m];
              return (
                <tr key={m} className="align-top">
                  <td className="py-2.5 pr-4">
                    <button type="button" onClick={() => setOpen(open === m ? null : m)} className="text-left hover:text-accent" aria-expanded={open === m}>
                      <span className="font-medium">{label}</span>
                      <span className="block text-xs text-ink-3">{better} is better. {desc}</span>
                    </button>
                  </td>
                  {algs.map((a) => {
                    const s = result.summary[m][a];
                    return (
                      <td key={a} className="py-2.5 pr-4 text-right whitespace-nowrap tabular-nums">
                        {fmt(s.mean)}
                        {s.half_width !== null && <span className="text-xs text-ink-3"> ± {fmt(s.half_width)}</span>}
                        <span className={cn("block text-xs", an.significant ? "font-semibold text-ink" : "text-ink-3")}>rank {fmt(an.mean_ranks[a])}</span>
                      </td>
                    );
                  })}
                  <td className="py-2.5 text-right text-xs whitespace-nowrap">
                    <span className={an.significant ? "font-medium text-[var(--st-implemented)]" : "text-ink-3"}>
                      {an.significant ? "Significant" : "Not significant"}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {open && <AnalysisDetail label={result.metric_info[open][0]} an={result.tests[open]} />}
      <div className="grid gap-8 md:grid-cols-2">
        {["slr", "speedup"].map((m) => (
          <DotWhisker key={m} title={result.metric_info[m][0]} unit="" rows={algs.map((a) => ({ label: ALG_LABEL[a] ?? a, summary: result.summary[m][a] }))} />
        ))}
      </div>
    </section>
  );
}
