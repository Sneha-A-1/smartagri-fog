import { CheckCircle2, CircleDashed, CircleHelp, XCircle } from "lucide-react";
import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { DotWhisker, fmt, ScenarioTimeline, type ScenarioEvent, type Summary } from "@/components/SimulationResults";
import { OriginBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";

type TestRow = { other: string; p_value: number; p_holm: number; a12: number | null; magnitude: string; significant: boolean; outcome: string };
type Evidence = { scenario: string; wins?: number; ties?: number; losses?: string[]; rows?: TestRow[]; verdict: string };

export type AuraEvaluationResult = {
  kind: "simulation.aura_evaluation";
  data_origin: string;
  params: { replications: number; duration_s: number; intensity: number; scenarios: string[] };
  scenario_info: Record<string, [string, string]>;
  events: Record<string, { events: ScenarioEvent[]; warnings: number; true_warnings: number; tasks: number }>;
  algorithms: string[];
  names: Record<string, string>;
  metrics: string[];
  metric_info: Record<string, [string, string, boolean]>;
  table: Record<string, Record<string, Record<string, Summary>>>;
  tests: Record<string, Record<string, { rows: TestRow[]; n: number }>>;
  hypotheses: { id: string; statement: string; verdict: string; how: string; evidence: Evidence[] }[];
  aura_logs: Record<string, {
    tier1: number; tier2: number; replicated: number; deferred: number; late_at_decision: number;
    reservation: { time_s: number; edge: number; fog: number; warned_gateways: number }[];
    explanations: { time_s: number; task: string; priority: string; effective_deadline_in_s: number;
      candidates: { node: string; score: number; finish_in_s: number; success_probability: number; value: number }[] }[];
  }>;
  runtime_s: Record<string, Summary>;
  summary: { scenarios: number; algorithms: number; replications: number; runs: number };
};

const VERDICT: Record<string, { icon: typeof CheckCircle2; cls: string }> = {
  supported: { icon: CheckCircle2, cls: "text-[var(--st-implemented)]" },
  "partly supported": { icon: CircleDashed, cls: "text-[var(--st-implemented)]" },
  mixed: { icon: CircleDashed, cls: "text-ink-2" },
  inconclusive: { icon: CircleHelp, cls: "text-ink-3" },
  "not supported": { icon: XCircle, cls: "text-danger" },
  "not tested": { icon: CircleHelp, cls: "text-ink-3" },
};

function Verdict({ v }: { v: string }) {
  const { icon: Icon, cls } = VERDICT[v] ?? VERDICT["not tested"];
  return (
    <span className={cn("inline-flex items-center gap-1 text-sm font-medium", cls)}>
      <Icon className="size-4" aria-hidden />
      {v.charAt(0).toUpperCase() + v.slice(1)}
    </span>
  );
}

const KEY_METRICS = ["urgent_deadline_success_rate", "aoi_violation_rate", "decision_value_pct", "energy_dynamic_j"];

export function AuraEvaluationView({ result }: { result: AuraEvaluationResult }) {
  const scenarios = Object.keys(result.table);
  const [sc, setSc] = useState(scenarios.find((s) => s !== "normal") ?? scenarios[0]);
  const name = (a: string) => result.names[a] ?? a;
  const auraName = name("aura");
  const outcome = (metric: string, a: string) =>
    a === "aura" ? null : result.tests[sc]?.[metric]?.rows.find((r) => r.other === name(a));
  const log = result.aura_logs[sc];
  const ev = result.events[sc];

  return (
    <div className="space-y-10">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold">AURA evaluation</h2>
          <OriginBadge origin={result.data_origin} />
        </div>
        <p className="mt-2 max-w-3xl text-sm text-ink-2">
          {result.summary.algorithms} algorithms on {result.summary.scenarios} scenarios, {result.summary.replications} seeded
          workloads each ({result.summary.runs} runs), {fmt(result.params.duration_s / 60)} simulated minutes per run at intensity{" "}
          {fmt(result.params.intensity)}. Every algorithm saw the same workloads. Each other algorithm is compared with AURA by a paired
          Wilcoxon test, Holm-corrected, with the A12 effect size.
        </p>
      </section>

      <section>
        <h3 className="font-semibold">Hypotheses</h3>
        <p className="mt-1 max-w-3xl text-xs text-ink-3">
          Verdicts are computed from the tests below. "Inconclusive" means no significant difference either way; with few replications
          that is expected, so use 30 for a paper.
        </p>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {result.hypotheses.map((h) => (
            <article key={h.id} className="rounded-xl border border-line bg-surface p-4">
              <div className="flex items-baseline justify-between gap-3">
                <h4 className="font-medium">{h.id}</h4>
                <Verdict v={h.verdict} />
              </div>
              <p className="mt-1 text-sm">{h.statement}</p>
              <p className="mt-2 text-xs text-ink-3">{h.how}</p>
              <ul className="mt-3 space-y-1 text-xs text-ink-2">
                {h.evidence.map((e) => (
                  <li key={e.scenario}>
                    <span className="font-medium">{result.scenario_info[e.scenario]?.[0] ?? e.scenario}:</span> {e.verdict}
                    {e.wins !== undefined && <> ({e.wins} better, {e.ties} no difference{e.losses?.length ? `, worse than ${e.losses.join(", ")}` : ""})</>}
                    {e.rows && <> ({e.rows.map((r) => `${r.other}: ${r.outcome}, A12 ${fmt(r.a12)}`).join("; ")})</>}
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>

      <section>
        <div className="flex flex-wrap gap-1 border-b border-line" role="tablist">
          {scenarios.map((s) => (
            <button key={s} role="tab" aria-selected={sc === s} onClick={() => setSc(s)}
              className={cn("-mb-px border-b-2 px-3 py-2 text-sm", sc === s ? "border-accent text-ink" : "border-transparent text-ink-2 hover:text-ink")}>
              {result.scenario_info[s]?.[0] ?? s}
            </button>
          ))}
        </div>
        <p className="mt-4 max-w-3xl text-sm text-ink-2">{result.scenario_info[sc]?.[1]}</p>
        {ev && (
          <>
            <ScenarioTimeline events={ev.events} duration={result.params.duration_s} stress={sc} />
            <p className="mt-2 text-xs text-ink-3">
              First workload: {ev.tasks.toLocaleString()} tasks
              {ev.warnings ? `, ${ev.warnings} early warnings of which ${ev.true_warnings} were followed by a surge` : ""}.
            </p>
          </>
        )}

        <div className="mt-6 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-ink-3">
              <tr className="border-b border-line">
                <th className="py-1.5 pr-3 font-normal">Algorithm</th>
                {result.metrics.map((m) => (
                  <th key={m} className="py-1.5 pr-3 text-right font-normal">
                    {result.metric_info[m][0]}
                    {result.metric_info[m][1] && <span className="block">({result.metric_info[m][1]})</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {result.algorithms.map((a) => (
                <tr key={a} className={a === "aura" ? "bg-accent-soft/40" : undefined}>
                  <td className="py-1.5 pr-3">{name(a)}</td>
                  {result.metrics.map((m) => {
                    const s = result.table[sc][a][m];
                    const o = outcome(m, a);
                    const mark = o?.outcome === "better" ? "▼" : o?.outcome === "worse" ? "▲" : "";
                    return (
                      <td key={m} className="py-1.5 pr-3 text-right tabular-nums"
                        title={o ? `AURA vs ${o.other}: ${o.outcome} (Holm p = ${fmt(o.p_holm)}, A12 = ${fmt(o.a12)})` : undefined}>
                        {fmt(s.mean)} <span className="text-ink-3">± {fmt(s.half_width)}</span>
                        {mark && <span className={cn("ml-1", mark === "▼" ? "text-[var(--st-implemented)]" : "text-danger")}>{mark}</span>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-ink-3">
          Mean ± 95% confidence interval. ▼ marks an algorithm AURA is significantly better than on that metric, ▲ one that is
          significantly better than AURA. Hover a cell for the test.
        </p>

        <div className="mt-8 grid max-w-5xl gap-6 lg:grid-cols-2">
          {KEY_METRICS.filter((m) => result.metrics.includes(m)).map((m) => (
            <DotWhisker key={m} title={`${result.metric_info[m][0]}, mean and 95% CI`} unit={result.metric_info[m][1]}
              rows={result.algorithms.map((a) => ({ label: name(a), summary: result.table[sc][a][m] }))} />
          ))}
        </div>
      </section>

      {log && (
        <section>
          <h3 className="font-semibold">Inside AURA ({result.scenario_info[sc]?.[0]}, first workload)</h3>
          <p className="mt-1 max-w-3xl text-sm text-ink-2">
            {log.tier1.toLocaleString()} tasks placed by the urgent tier and {log.tier2.toLocaleString()} by the strategic tier;{" "}
            {log.replicated} critical tasks replicated; {log.deferred} strategic tasks deferred while no node was reachable;{" "}
            {log.late_at_decision.toLocaleString()} tasks could not meet their effective deadline on any node when they arrived.
          </p>
          {log.reservation.length > 0 && (
            <div className="mt-4 max-w-4xl">
              <h4 className="text-sm font-medium">Capacity reserved for urgent work (mean share per node)</h4>
              <div className="mt-2 h-56">
                <ResponsiveContainer>
                  <LineChart data={log.reservation.map((r) => ({ t: r.time_s / 60, edge: 100 * r.edge, fog: 100 * r.fog, warned: r.warned_gateways }))}
                    margin={{ top: 8, right: 16, bottom: 18, left: 0 }}>
                    <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
                    {ev?.events.map((e) => (
                      <ReferenceArea key={e.label} x1={e.start_s / 60} x2={Math.min(e.end_s, result.params.duration_s) / 60}
                        fill={e.kind === "outage" ? "var(--danger)" : "var(--series-2)"} fillOpacity={0.12} />
                    ))}
                    <XAxis dataKey="t" type="number" domain={[0, result.params.duration_s / 60]} tick={{ fill: "var(--ink-3)", fontSize: 11 }}
                      stroke="var(--line)" label={{ value: "Simulated minutes (shaded: scenario event)", position: "insideBottom", offset: -10, fill: "var(--ink-3)", fontSize: 11 }} />
                    <YAxis domain={[0, 100]} unit="%" tick={{ fill: "var(--ink-3)", fontSize: 11 }} stroke="var(--line)" width={44} />
                    <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                      labelFormatter={(t) => `${fmt(Number(t))} min`}
                      formatter={(v, k, item) => k === "edge" || k === "fog"
                        ? [`${fmt(Number(v))}%${k === "edge" ? ` (warned gateways: ${(item?.payload as { warned: number }).warned})` : ""}`, k === "edge" ? "Edge" : "Fog"]
                        : [String(v), String(k)]} />
                    <Legend wrapperStyle={{ fontSize: 12, paddingTop: 18 }} formatter={(k: string) => <span className="text-ink-2">{k === "edge" ? "Edge devices" : "Fog servers"}</span>} />
                    <Line dataKey="edge" type="stepAfter" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
                    <Line dataKey="fog" type="stepAfter" stroke="var(--series-3)" strokeWidth={2} dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
          {log.explanations.length > 0 && (
            <div className="mt-6 max-w-4xl">
              <h4 className="text-sm font-medium">Why this node? Sample urgent decisions</h4>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-ink-3">
                    <tr className="border-b border-line">
                      <th className="py-1.5 pr-3 font-normal">Time (s)</th>
                      <th className="py-1.5 pr-3 font-normal">Task</th>
                      <th className="py-1.5 pr-3 text-right font-normal">Effective deadline in (s)</th>
                      <th className="py-1.5 pr-3 font-normal">Best three nodes: score (finish in s, success probability)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {log.explanations.map((x) => (
                      <tr key={x.time_s + x.task}>
                        <td className="py-1.5 pr-3 tabular-nums">{fmt(x.time_s)}</td>
                        <td className="py-1.5 pr-3">{x.task.replaceAll("_", " ")} ({x.priority})</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(x.effective_deadline_in_s)}</td>
                        <td className="py-1.5 pr-3 text-xs">
                          {x.candidates.map((c, i) => (
                            <span key={c.node} className={i === 0 ? "font-medium" : "text-ink-2"}>
                              {i > 0 && " · "}{c.node}: {fmt(c.score)} ({fmt(c.finish_in_s)} s, {fmt(c.success_probability)})
                            </span>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-ink-3">Score = success probability × decision value − energy and cost penalties. The first node won.</p>
            </div>
          )}
        </section>
      )}

      <section>
        <h3 className="font-semibold">Run time per simulation</h3>
        <p className="mt-1 text-xs text-ink-3">Wall-clock seconds on the computer that ran this job, including the simulator.</p>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          {result.algorithms.map((a) => (
            <span key={a}>{name(a)}: <span className="tabular-nums">{fmt(result.runtime_s[a].mean)} s</span></span>
          ))}
        </div>
        <p className="mt-4 text-xs text-ink-3">
          Not implemented in this version of {auraName}: preempting a running task and switching to a light variant of a task.
        </p>
      </section>
    </div>
  );
}
