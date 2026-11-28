import { OriginBadge } from "./StatusBadge";
import { optionLabel } from "./SchemaForm";

type MetricInfo = Record<string, [label: string, unit: string, higherIsBetter: boolean]>;
export type Summary = { n: number; mean: number | null; std: number | null; ci_low: number | null; ci_high: number | null; half_width: number | null };

export type SingleRunResult = {
  kind: "simulation.single_run";
  data_origin: string;
  metric_info: MetricInfo;
  metrics: Record<string, number | null>;
  nodes?: NodeRow[];
  provenance: Record<string, unknown>;
};

type NodeRow = { id: string; layer: string; cores: number; mips: number; utilization: number; tasks_done: number; energy_j: number; dynamic_energy_j: number; failures: number; availability: number };

export type ComparisonResult = {
  kind: "simulation.comparison";
  data_origin: string;
  metric_info: MetricInfo;
  headline_metrics: string[];
  comparison: Record<string, Record<string, Summary>>;
  params: { replications: number; discipline: string; placements: string[] };
  provenance: Record<string, unknown>;
};

export function fmt(v: number | null | undefined, unit = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const abs = Math.abs(v);
  const digits = abs >= 1000 ? 0 : abs >= 100 ? 1 : abs >= 10 ? 2 : 3;
  const s = v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
  return unit === "%" ? `${s}%` : s;
}

const GROUPS: [string, string[]][] = [
  ["Deadlines and completion", ["tasks_total", "completion_rate", "deadline_success_rate", "urgent_deadline_success_rate"]],
  ["Time", ["mean_response_s", "p95_response_s", "urgent_mean_response_s", "mean_wait_s", "mean_exec_s", "mean_transfer_s", "makespan_s"]],
  ["Energy and cost", ["energy_dynamic_j", "energy_total_j", "energy_per_task_j", "energy_edge_j", "energy_fog_j", "energy_cloud_j", "cost"]],
  ["Network", ["bytes_total_mb", "bytes_cloud_mb", "network_usage"]],
  ["Where tasks ran", ["share_edge", "share_fog", "share_cloud", "utilization_edge", "utilization_fog", "utilization_cloud", "load_balance_cv"]],
  ["Scheduler and reliability", ["scheduling_overhead_us", "node_failures"]],
];

export function SingleRunView({ result }: { result: SingleRunResult }) {
  return (
    <section className="mt-10">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold">Results of this run</h2>
        <OriginBadge origin={result.data_origin} />
      </div>
      <p className="mt-1 max-w-2xl text-sm text-ink-2">
        One simulated run. A single run can't show whether one policy is better than another; use the comparison
        plugin, which repeats runs with different seeds and reports confidence intervals.
      </p>
      <div className="mt-6 grid gap-x-10 gap-y-8 md:grid-cols-2">
        {GROUPS.map(([title, keys]) => (
          <div key={title}>
            <h3 className="text-sm font-medium text-ink-2">{title}</h3>
            <dl className="mt-2 divide-y divide-line border-y border-line text-sm">
              {keys.map((k) => {
                const [label, unit] = result.metric_info[k] ?? [k, ""];
                return (
                  <div key={k} className="flex justify-between gap-4 py-1.5">
                    <dt className="text-ink-2">{label}</dt>
                    <dd className="tabular-nums">
                      {fmt(result.metrics[k], unit)}
                      {unit && unit !== "%" && <span className="ml-1 text-ink-3">{unit}</span>}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>
        ))}
      </div>
      {result.nodes && result.nodes.length > 0 && <NodeTable nodes={result.nodes} />}
      <Provenance provenance={result.provenance} />
    </section>
  );
}

function NodeTable({ nodes }: { nodes: NodeRow[] }) {
  return (
    <div className="mt-10">
      <h3 className="text-sm font-medium text-ink-2">Per device</h3>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[40rem] text-sm">
          <thead className="text-left text-xs text-ink-3">
            <tr className="border-b border-line">
              <th className="py-1.5 pr-3 font-normal">Device</th>
              <th className="py-1.5 pr-3 font-normal">Layer</th>
              <th className="w-48 py-1.5 pr-3 font-normal">Utilisation</th>
              <th className="py-1.5 pr-3 text-right font-normal">Tasks run</th>
              <th className="py-1.5 pr-3 text-right font-normal">Energy (J)</th>
              <th className="py-1.5 pr-3 text-right font-normal">Failures</th>
              <th className="py-1.5 text-right font-normal">Available</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {nodes.map((n) => (
              <tr key={n.id}>
                <td className="py-1.5 pr-3">{n.id}</td>
                <td className="py-1.5 pr-3 capitalize text-ink-2">{n.layer}</td>
                <td className="py-1.5 pr-3">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, n.utilization)}%` }} /></div>
                    <span className="w-12 text-right tabular-nums text-xs">{fmt(n.utilization)}%</span>
                  </div>
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{n.tasks_done.toLocaleString()}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(n.energy_j)}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{n.failures}</td>
                <td className="py-1.5 text-right tabular-nums">{fmt(n.availability)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ComparisonView({ result }: { result: ComparisonResult }) {
  const policies = result.params.placements;
  const chart = (metric: string) => {
    const [label, unit] = result.metric_info[metric];
    return (
      <DotWhisker
        key={metric}
        title={label}
        unit={unit}
        rows={policies.map((p) => ({ label: optionLabel(p), summary: result.comparison[p][metric] }))}
      />
    );
  };

  return (
    <section className="mt-10">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold">Comparison of placement policies</h2>
        <OriginBadge origin={result.data_origin} />
      </div>
      <p className="mt-1 max-w-3xl text-sm text-ink-2">
        Each value is the mean of {result.params.replications} replications with a 95% confidence interval. Every
        policy saw exactly the same workloads, and every node used {optionLabel(result.params.discipline)}.
        Overlapping intervals mean the data can't separate the policies. Formal significance tests arrive in Phase 1b,
        so no policy is ranked here.
      </p>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[48rem] text-sm">
          <thead className="text-left text-ink-3">
            <tr className="border-b border-line align-bottom">
              <th className="py-2 pr-4 font-normal">Policy</th>
              {result.headline_metrics.map((m) => {
                const [label, unit] = result.metric_info[m];
                return (
                  <th key={m} className="py-2 pr-4 text-right font-normal">
                    {label}
                    {unit && <span className="block text-xs">{unit}</span>}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {policies.map((p) => (
              <tr key={p}>
                <td className="py-2 pr-4 font-medium whitespace-nowrap">{optionLabel(p)}</td>
                {result.headline_metrics.map((m) => {
                  const s = result.comparison[p][m];
                  return (
                    <td key={m} className="py-2 pr-4 text-right whitespace-nowrap tabular-nums">
                      {fmt(s.mean)}
                      {s.half_width !== null && <span className="text-xs text-ink-3"> ± {fmt(s.half_width)}</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-10 grid gap-8 md:grid-cols-2">
        {["deadline_success_rate", "urgent_deadline_success_rate", "mean_response_s", "energy_dynamic_j"].map(chart)}
      </div>
      <Provenance provenance={result.provenance} />
    </section>
  );
}

export function Provenance({ provenance }: { provenance: Record<string, unknown> }) {
  return (
    <details className="mt-8 text-sm">
      <summary className="cursor-pointer text-ink-2">Reproducibility details</summary>
      <p className="mt-2 text-ink-3">
        Fingerprints of the exact topology and workload traces used. Re-running with the same parameters gives the
        same fingerprints and the same results (except the measured scheduler decision time).
      </p>
      <pre className="mt-2 overflow-x-auto rounded-lg border border-line bg-surface p-3 text-xs">
        {JSON.stringify(provenance, null, 2)}
      </pre>
    </details>
  );
}

/** Mean (dot) with 95% confidence interval (whisker) per policy, on a shared horizontal scale. */
export function DotWhisker({ title, unit, rows }: { title: string; unit: string; rows: { label: string; summary: Summary }[] }) {
  const lows = rows.map((r) => r.summary.ci_low ?? r.summary.mean ?? 0);
  const highs = rows.map((r) => r.summary.ci_high ?? r.summary.mean ?? 0);
  let lo = Math.min(...lows);
  let hi = Math.max(...highs);
  if (hi - lo < 1e-9) {
    lo -= 1;
    hi += 1;
  }
  const pad = (hi - lo) * 0.08;
  lo -= pad;
  hi += pad;
  const W = 520;
  // Room for the longest label (about 6.6 viewBox units per character at this font size).
  const labelW = Math.max(120, Math.min(260, Math.max(...rows.map((r) => r.label.length)) * 6.6 + 16));
  const rowH = 26;
  const H = rows.length * rowH + 28;
  const x = (v: number) => labelW + ((v - lo) / (hi - lo)) * (W - labelW - 16);
  const ticks = niceTicks(lo, hi, 4);

  return (
    <figure>
      <figcaption className="text-sm font-medium">
        {title}
        {unit && <span className="font-normal text-ink-3"> ({unit})</span>}
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full" role="img" aria-label={`${title}: mean and 95% confidence interval per policy`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={0} y2={rows.length * rowH} stroke="var(--line)" />
            <text x={x(t)} y={rows.length * rowH + 16} textAnchor="middle" fontSize={11} fill="var(--ink-3)">
              {fmt(t)}
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          const y = i * rowH + rowH / 2;
          const m = r.summary.mean;
          return (
            <g key={r.label}>
              <text x={labelW - 10} y={y + 4} textAnchor="end" fontSize={12} fill="var(--ink)">
                {r.label}
              </text>
              {r.summary.ci_low !== null && r.summary.ci_high !== null && (
                <line x1={x(r.summary.ci_low)} x2={x(r.summary.ci_high)} y1={y} y2={y} stroke="var(--ink-2)" strokeWidth={1.5} />
              )}
              {m !== null && <circle cx={x(m)} cy={y} r={4} fill="var(--accent)" />}
              <title>{`${r.label}: ${fmt(m)} (95% CI ${fmt(r.summary.ci_low)} to ${fmt(r.summary.ci_high)})`}</title>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

/** Round tick values ("nice numbers") covering [lo, hi]. */
function niceTicks(lo: number, hi: number, target: number): number[] {
  const raw = (hi - lo) / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => s >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(Number(t.toPrecision(12)));
  return out;
}
