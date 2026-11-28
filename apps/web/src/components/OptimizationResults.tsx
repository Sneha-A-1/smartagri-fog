import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { AnalysisDetail, type ExperimentResult } from "@/components/ExperimentResults";
import { DotWhisker, fmt, type Summary } from "@/components/SimulationResults";
import { OriginBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";

type Analysis = ExperimentResult["analysis"][string];
type Objectives = Record<string, number>;

export type OptimizerBenchmarkResult = {
  kind: "simulation.optimizer_benchmark";
  data_origin: string;
  params: { budget: number; pop_size: number; replications: number; instances: number; seed_heuristics: boolean; algorithms: string[] };
  objective_info: Record<string, [string, string]>;
  names: Record<string, string>;
  instances: { index: number; time_s: number; tasks: number; nodes: number; log10_space: number; min_min_fitness: number; unavoidable_weighted_miss: number }[];
  table: Record<
    string,
    {
      name: string;
      fitness: Summary;
      improvement_vs_min_min_pct: Summary | null;
      better_than_min_min_pct: number | null;
      runtime_ms: Summary | null;
      objectives: Record<string, Summary>;
    }
  >;
  stats: Record<string, Analysis>;
  convergence: { evaluations: number[]; mean: Record<string, (number | null)[]>; reference: Record<string, number> };
  pareto: { front: Objectives[]; points: Record<string, Objectives> } | null;
  provenance: Record<string, unknown>;
  summary: { instances: number; replications: number; runs: number; budget: number; best_mean_fitness: string; verdict: string };
};

/** Fixed colour per optimiser (colour follows the entity, never its rank). Baselines are neutral references. */
export const OPT_COLORS: Record<string, string> = {
  ga: "var(--series-1)",
  pso: "var(--series-2)",
  aco: "var(--series-3)",
  gwo: "var(--series-4)",
  woa: "var(--series-5)",
  nsga2: "var(--series-6)",
  random_search: "var(--ink-3)",
};
const BASELINES = ["min_min", "greedy_mct"];
/** Like fmt, but keeps very small non-zero values (such as cloud cost per window) readable. */
const fmtSmall = (v: number) => (v !== 0 && Math.abs(v) < 0.001 ? v.toExponential(2) : fmt(v));
const tooltipStyle = { background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12, color: "var(--ink)" };
const axisTick = { fill: "var(--ink-3)", fontSize: 11 };

export function OptimizerBenchmarkView({ result }: { result: OptimizerBenchmarkResult }) {
  const [metric, setMetric] = useState("fitness");
  const algs = Object.keys(result.table);
  const opts = algs.filter((a) => !BASELINES.includes(a));
  const ranks = result.stats.fitness.mean_ranks as Record<string, number>;
  const metricLabel: Record<string, string> = {
    fitness: "Weighted fitness",
    weighted_miss: result.objective_info.weighted_miss[0],
    energy_j: result.objective_info.energy_j[0],
  };
  const unavoidable = result.instances.reduce((s, i) => s + i.unavoidable_weighted_miss, 0) / Math.max(result.instances.length, 1);

  return (
    <div className="space-y-10">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold">Optimiser benchmark</h2>
          <OriginBadge origin={result.data_origin} />
        </div>
        <p className="mt-2 max-w-3xl text-sm text-ink-2">
          {result.summary.instances} scheduling windows from a simulated farm network, {result.summary.replications} seeded runs per
          optimiser and window, {result.summary.budget.toLocaleString()} objective evaluations per run
          {result.params.seed_heuristics ? ", starting from Min-Min and greedy MCT" : ", random starting populations"}.{" "}
          {result.summary.verdict} Lowest mean fitness: {result.summary.best_mean_fitness}.
        </p>
        <p className="mt-2 max-w-3xl text-xs text-ink-3">
          Fitness is the scheduler's own estimate for a window (lower is better), not a simulated outcome. On average{" "}
          {fmt(100 * unavoidable)}% of the priority-weighted tasks in these windows could not meet their deadline on any node,
          so no optimiser can remove those misses. To see end-to-end effects, compare the batch placements in Experiments.
        </p>
      </section>

      <section className="space-y-8">
        <div>
          <h3 className="font-semibold">Convergence</h3>
          <p className="mt-1 text-xs text-ink-3">Best fitness found so far, averaged over every window and run. Dashed lines: Min-Min and greedy MCT.</p>
          <div className="mt-3 h-80">
            <ResponsiveContainer>
              <LineChart
                data={result.convergence.evaluations.map((e, i) => ({
                  e,
                  ...Object.fromEntries(opts.map((a) => [a, result.convergence.mean[a]?.[i] ?? null])),
                }))}
                margin={{ top: 8, right: 16, bottom: 26, left: 4 }}
              >
                <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
                <XAxis dataKey="e" type="number" domain={["dataMin", "dataMax"]} tick={axisTick} stroke="var(--line)"
                  label={{ value: "Objective evaluations", position: "insideBottom", offset: -10, fill: "var(--ink-3)", fontSize: 11 }} />
                <YAxis tick={axisTick} stroke="var(--line)" domain={["auto", "auto"]} width={56} tickFormatter={(v: number) => v.toFixed(3)} />
                <Tooltip contentStyle={tooltipStyle} labelFormatter={(e) => `${e} evaluations`}
                  formatter={(v, k) => [Number(v).toFixed(4), result.names[String(k)] ?? String(k)]} />
                <Legend wrapperStyle={{ fontSize: 12, paddingTop: 22 }} formatter={(k: string) => <span className="text-ink-2">{result.names[k] ?? k}</span>} />
                {BASELINES.map((b) => (
                  <ReferenceLine key={b} y={result.convergence.reference[b]} stroke="var(--ink-3)" strokeDasharray="5 4"
                    label={{ value: result.names[b], position: "insideTopRight", fill: "var(--ink-3)", fontSize: 11 }} />
                ))}
                {opts.map((a) => (
                  <Line key={a} dataKey={a} stroke={OPT_COLORS[a]} strokeWidth={2} dot={false}
                    strokeDasharray={a === "random_search" ? "3 3" : undefined} isAnimationActive={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="max-w-3xl">
          <DotWhisker
            title="Final fitness, mean and 95% confidence interval (lower is better)"
            unit=""
            rows={algs.map((a) => ({ label: result.names[a], summary: result.table[a].fitness }))}
          />
        </div>
      </section>

      <section>
        <h3 className="font-semibold">Results per optimiser</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-ink-3">
              <tr className="border-b border-line">
                <th className="py-1.5 pr-3 font-normal">Optimiser</th>
                <th className="py-1.5 pr-3 text-right font-normal">Fitness</th>
                <th className="py-1.5 pr-3 text-right font-normal">Mean rank</th>
                <th className="py-1.5 pr-3 text-right font-normal">Gain over Min-Min</th>
                <th className="py-1.5 pr-3 text-right font-normal">Runs better than Min-Min</th>
                <th className="py-1.5 pr-3 text-right font-normal">Weighted misses</th>
                <th className="py-1.5 pr-3 text-right font-normal">Response (s)</th>
                <th className="py-1.5 pr-3 text-right font-normal">Energy (J)</th>
                <th className="py-1.5 text-right font-normal">Run time (ms)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {algs.map((a) => {
                const t = result.table[a];
                return (
                  <tr key={a}>
                    <td className="py-1.5 pr-3">
                      <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full align-middle"
                        style={{ background: OPT_COLORS[a] ?? "transparent", border: OPT_COLORS[a] ? undefined : "1.5px dashed var(--ink-3)" }} />
                      {t.name}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(t.fitness.mean)} <span className="text-ink-3">± {fmt(t.fitness.half_width)}</span></td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(ranks[t.name])}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{a === "min_min" ? "–" : `${fmt(t.improvement_vs_min_min_pct?.mean)}%`}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{a === "min_min" ? "–" : `${fmt(t.better_than_min_min_pct)}%`}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(100 * (t.objectives.weighted_miss.mean ?? 0))}%</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(t.objectives.mean_response_s.mean)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(t.objectives.energy_j.mean)}</td>
                    <td className="py-1.5 text-right tabular-nums">{t.runtime_ms ? fmt(t.runtime_ms.mean) : "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-ink-3">
          Run times were measured on the computer that ran this job and depend on it. Mean rank 1 is best (Friedman ranks over every
          window and run).
        </p>
      </section>

      {result.pareto && <ParetoView result={result} pareto={result.pareto} />}

      <section>
        <h3 className="font-semibold">Statistics</h3>
        <div className="mt-3 flex flex-wrap gap-2" role="tablist">
          {Object.keys(result.stats).map((m) => (
            <button key={m} role="tab" aria-selected={metric === m} onClick={() => setMetric(m)}
              className={cn("rounded-full border px-3 py-1 text-xs", metric === m ? "border-accent bg-accent-soft text-ink" : "border-line text-ink-2 hover:border-ink-3")}>
              {metricLabel[m] ?? m}
            </button>
          ))}
        </div>
        <div className="mt-4">
          <AnalysisDetail label={metricLabel[metric] ?? metric} an={result.stats[metric]} />
        </div>
      </section>

      <section>
        <h3 className="font-semibold">Benchmark windows</h3>
        <table className="mt-3 w-full text-sm">
          <thead className="text-left text-ink-3">
            <tr className="border-b border-line">
              <th className="py-1.5 pr-3 font-normal">Window</th>
              <th className="py-1.5 pr-3 text-right font-normal">Simulated time (s)</th>
              <th className="py-1.5 pr-3 text-right font-normal">Tasks</th>
              <th className="py-1.5 pr-3 text-right font-normal">Nodes</th>
              <th className="py-1.5 pr-3 text-right font-normal">Possible assignments</th>
              <th className="py-1.5 pr-3 text-right font-normal">Unavoidable misses</th>
              <th className="py-1.5 text-right font-normal">Min-Min fitness</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {result.instances.map((i) => (
              <tr key={i.index}>
                <td className="py-1.5 pr-3">{i.index + 1}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(i.time_s)}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{i.tasks}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{i.nodes}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">10<sup>{Math.round(i.log10_space)}</sup></td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(100 * i.unavoidable_weighted_miss)}%</td>
                <td className="py-1.5 text-right tabular-nums">{fmt(i.min_min_fitness)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function ParetoView({ result, pareto }: { result: OptimizerBenchmarkResult; pareto: NonNullable<OptimizerBenchmarkResult["pareto"]> }) {
  const objs = Object.keys(result.objective_info);
  const [x, setX] = useState("energy_j");
  const [y, setY] = useState("mean_response_s");
  const label = (k: string) => {
    const [name, unit] = result.objective_info[k];
    return unit === "share" ? `${name} (%)` : `${name} (${unit})`;
  };
  const val = (o: Objectives, k: string) => (result.objective_info[k][1] === "share" ? 100 * o[k] : o[k]);
  const front = pareto.front.map((o) => ({ x: val(o, x), y: val(o, y) })).sort((a, b) => a.x - b.x);
  // Methods that returned the same point share one marker and one label, so labels never overlap.
  const grouped = new Map<string, { x: number; y: number; names: string[] }>();
  for (const [a, o] of Object.entries(pareto.points)) {
    const px = val(o, x);
    const py = val(o, y);
    const key = `${px.toPrecision(6)}|${py.toPrecision(6)}`;
    const g = grouped.get(key) ?? { x: px, y: py, names: [] };
    g.names.push(result.names[a] ?? a);
    grouped.set(key, g);
  }
  const points = [...grouped.values()].map((g) => ({ x: g.x, y: g.y, name: g.names.join(", ") }));
  // Table of every method's answer on all four objectives, grouping identical answers.
  const byAnswer = new Map<string, { names: string[]; o: Objectives }>();
  for (const [a, o] of Object.entries(pareto.points)) {
    const key = objs.map((k) => o[k].toPrecision(6)).join("|");
    const g = byAnswer.get(key) ?? { names: [], o };
    g.names.push(result.names[a] ?? a);
    byAnswer.set(key, g);
  }
  const answerRows = [...byAnswer.values()].map((g) => ({ names: g.names.join(", "), o: g.o }));
  const select = (value: string, onChange: (v: string) => void, aria: string) => (
    <select aria-label={aria} value={value} onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-line bg-surface px-2 py-1 text-xs">
      {objs.map((k) => (
        <option key={k} value={k}>{result.objective_info[k][0]}</option>
      ))}
    </select>
  );

  return (
    <section>
      <h3 className="font-semibold">NSGA-II Pareto front</h3>
      <p className="mt-1 max-w-3xl text-xs text-ink-3">
        First window, first run. Each dot is a mapping NSGA-II found that no other mapping it evaluated beats on all four
        objectives (misses, response, energy, cost). Diamonds are the single answer each method returned for the same window,
        listed in the table below. The chart is a two-dimensional view of four objectives, so some front members look dominated.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink-2">
        Horizontal {select(x, setX, "Horizontal axis")} vertical {select(y, setY, "Vertical axis")}
      </div>
      <div className="mt-3 h-80">
        <ResponsiveContainer>
          <ScatterChart margin={{ top: 12, right: 24, bottom: 24, left: 8 }}>
            <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" />
            <XAxis dataKey="x" type="number" domain={["auto", "auto"]} tick={axisTick} stroke="var(--line)" tickFormatter={(v: number) => fmt(v)}
              label={{ value: label(x), position: "insideBottom", offset: -14, fill: "var(--ink-3)", fontSize: 11 }} />
            <YAxis dataKey="y" type="number" domain={["auto", "auto"]} tick={axisTick} stroke="var(--line)" width={60} tickFormatter={(v: number) => fmt(v)}
              label={{ value: label(y), angle: -90, position: "insideLeft", fill: "var(--ink-3)", fontSize: 11, dy: 50 }} />
            <ZAxis range={[72, 72]} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: "3 3" }}
              labelFormatter={() => ""}
              formatter={(v, k, item) => {
                const names = (item?.payload as { name?: string } | undefined)?.name;
                const row = [fmt(Number(v)), k === "x" ? label(x) : label(y)] as [string, string];
                return names && k === "x" ? [`${row[0]} (${names})`, row[1]] : row;
              }} />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
            <Scatter name="NSGA-II front" data={front} fill="var(--series-6)" stroke="var(--surface)" strokeWidth={2} isAnimationActive={false} />
            <Scatter name="Answer returned by a method (hover for names)" data={points} fill="none" stroke="var(--ink)"
              strokeWidth={2} shape="diamond" isAnimationActive={false} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <table className="mt-4 w-full max-w-3xl text-sm">
        <thead className="text-left text-ink-3">
          <tr className="border-b border-line">
            <th className="py-1.5 pr-3 font-normal">Answer returned by</th>
            {objs.map((k) => (
              <th key={k} className="py-1.5 pr-3 text-right font-normal">{label(k)}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {answerRows.map((r) => (
            <tr key={r.names}>
              <td className="py-1.5 pr-3">{r.names}</td>
              {objs.map((k) => (
                <td key={k} className="py-1.5 pr-3 text-right tabular-nums">{fmtSmall(val(r.o, k))}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
