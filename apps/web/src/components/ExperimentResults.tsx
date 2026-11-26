import { useState } from "react";
import { cn } from "@/lib/cn";
import { DotWhisker, fmt, Provenance, type Summary } from "./SimulationResults";
import { OriginBadge } from "./StatusBadge";

type Pair = {
  a: string;
  b: string;
  p_value: number;
  p_holm: number;
  a12: number | null;
  magnitude: string;
  significant: boolean;
  better: string | null;
};

type Analysis = {
  n: number;
  higher_is_better: boolean;
  summaries: Record<string, Summary>;
  mean_ranks: Record<string, number | null>;
  rank_order: string[];
  omnibus: { test: string | null; statistic: number | null; p_value: number | null; critical_difference: number | null };
  pairwise: Pair[];
  significant: boolean;
  verdict: string;
};

export type ExperimentResult = {
  kind: "experiment";
  data_origin: string;
  spec: { name: string; replications: number; alpha: number };
  spec_sha256: string;
  algorithms: string[];
  metric_info: Record<string, [string, string, boolean]>;
  headline_metrics: string[];
  analysis: Record<string, Analysis>;
  provenance: Record<string, unknown>;
};

const p = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v < 0.001 ? "< 0.001" : v.toFixed(3));
/** "p < 0.001" or "p = 0.042" */
const pText = (v: number | null | undefined) => {
  const s = p(v);
  return s.startsWith("<") ? `p ${s}` : `p = ${s}`;
};

export function ExperimentResults({ result, exportBase }: { result: ExperimentResult; exportBase: string }) {
  const [open, setOpen] = useState<string | null>(null);
  const metrics = result.headline_metrics;
  const n = result.spec.replications;

  return (
    <section className="mt-10 space-y-10">
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-lg font-semibold">Results</h2>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <OriginBadge origin={result.data_origin} />
            <span className="text-ink-3">Download:</span>
            {(["csv", "tex", "json", "yaml"] as const).map((fmtKey) => (
              <a key={fmtKey} href={`${exportBase}/${fmtKey}`} download className="rounded-md border border-line px-2 py-0.5 text-ink-2 hover:bg-surface-2">
                {{ csv: "CSV (all runs)", tex: "LaTeX tables", json: "JSON", yaml: "Experiment file" }[fmtKey]}
              </a>
            ))}
          </div>
        </div>
        <p className="mt-2 max-w-3xl text-sm text-ink-2">
          {result.algorithms.length} algorithms, {n} paired replications each (every algorithm saw the same workloads).
          Differences are tested with the Friedman test, with Holm-corrected Wilcoxon tests for each pair, at α ={" "}
          {result.spec.alpha}. A rank is shown in bold only when the test finds a significant difference. Significant
          does not mean large: a tiny but consistent gap can be significant, so check the effect sizes by clicking a
          metric before claiming a practical improvement.
          {n < 10 && " With fewer than 10 replications, pairwise tests rarely reach significance; use 30 for papers."}
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[52rem] text-sm">
          <thead className="text-left text-ink-3">
            <tr className="border-b border-line align-bottom">
              <th className="py-2 pr-4 font-normal">Metric</th>
              {result.algorithms.map((a) => (
                <th key={a} className="py-2 pr-4 text-right font-normal">{a}</th>
              ))}
              <th className="py-2 pr-2 text-right font-normal">Test</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {metrics.map((m) => {
              const an = result.analysis[m];
              const [label, unit, higher] = result.metric_info[m];
              return (
                <tr key={m} className="align-top">
                  <td className="py-2.5 pr-4">
                    <button type="button" onClick={() => setOpen(open === m ? null : m)} className="text-left hover:text-accent" aria-expanded={open === m}>
                      <span className="font-medium">{label}</span>
                      <span className="block text-xs text-ink-3">
                        {unit && `${unit}, `}
                        {higher ? "higher is better" : "lower is better"}
                      </span>
                    </button>
                  </td>
                  {result.algorithms.map((a) => {
                    const s = an.summaries[a];
                    const rank = an.mean_ranks[a];
                    return (
                      <td key={a} className="py-2.5 pr-4 text-right whitespace-nowrap tabular-nums">
                        {fmt(s.mean)}
                        {s.half_width !== null && <span className="text-xs text-ink-3"> ± {fmt(s.half_width)}</span>}
                        <span className={cn("block text-xs", an.significant ? "font-semibold text-ink" : "text-ink-3")}>
                          rank {fmt(rank)}
                        </span>
                      </td>
                    );
                  })}
                  <td className="py-2.5 pr-2 text-right text-xs whitespace-nowrap">
                    <span className={an.significant ? "font-medium text-[var(--st-implemented)]" : "text-ink-3"}>
                      {an.significant ? "Significant" : "Not significant"}
                    </span>
                    <span className="block text-ink-3">{pText(an.omnibus.p_value ?? an.pairwise[0]?.p_holm)}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-ink-3">Click a metric to see its verdict and every pairwise comparison.</p>
      </div>

      {open && <MetricDetail metric={open} result={result} />}

      <div className="grid gap-8 md:grid-cols-2">
        {["deadline_success_rate", "urgent_deadline_success_rate", "mean_response_s", "energy_dynamic_j"]
          .filter((m) => result.analysis[m])
          .map((m) => (
            <DotWhisker
              key={m}
              title={result.metric_info[m][0]}
              unit={result.metric_info[m][1]}
              rows={result.algorithms.map((a) => ({ label: a, summary: result.analysis[m].summaries[a] }))}
            />
          ))}
      </div>

      <Provenance provenance={{ spec_sha256: result.spec_sha256, ...result.provenance }} />
    </section>
  );
}

function MetricDetail({ metric, result }: { metric: string; result: ExperimentResult }) {
  return <AnalysisDetail label={result.metric_info[metric][0]} an={result.analysis[metric]} />;
}

/** Verdict, omnibus test and every pairwise comparison for one metric (output of smartagri_core.stats.compare). */
export function AnalysisDetail({ label, an }: { label: string; an: ExperimentResult["analysis"][string] }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-5">
      <h3 className="font-semibold">{label}</h3>
      <p className="mt-1 text-sm text-ink-2">{an.verdict}</p>
      {an.omnibus.test && (
        <p className="mt-1 text-xs text-ink-3">
          Friedman χ² = {fmt(an.omnibus.statistic)}, {pText(an.omnibus.p_value)}, Nemenyi critical difference = {fmt(an.omnibus.critical_difference)}{" "}
          (mean ranks further apart than this differ significantly).
        </p>
      )}
      <table className="mt-4 w-full text-sm">
        <thead className="text-left text-ink-3">
          <tr className="border-b border-line">
            <th className="py-1.5 pr-3 font-normal">Pair</th>
            <th className="py-1.5 pr-3 text-right font-normal">p (Holm)</th>
            <th className="py-1.5 pr-3 text-right font-normal">A₁₂</th>
            <th className="py-1.5 pr-3 font-normal">Effect size</th>
            <th className="py-1.5 font-normal">Result</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {an.pairwise.map((pair) => (
            <tr key={`${pair.a}-${pair.b}`}>
              <td className="py-1.5 pr-3">{pair.a} vs {pair.b}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{p(pair.p_holm)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(pair.a12)}</td>
              <td className="py-1.5 pr-3">{pair.magnitude}</td>
              <td className="py-1.5">{pair.significant ? <span className="font-medium">{pair.better} is better</span> : <span className="text-ink-3">no significant difference</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-ink-3">
        A₁₂ is the probability that a run of the first algorithm is better than a run of the second (0.5 = no difference).
      </p>
    </div>
  );
}
