import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useJob, useJobResult, useJobs, useStartJob } from "@/api/hooks";
import { type AuraEvaluationResult, AuraEvaluationView } from "@/components/AuraResults";
import { Button } from "@/components/Button";
import { PageHeader } from "@/components/PageHeader";
import { ProgressBar } from "@/components/ProgressBar";
import { formatTime } from "@/lib/format";

const PLUGIN = "simulation:aura_evaluation";

const SCENARIOS: [string, string][] = [
  ["normal", "Normal load with data freshness"],
  ["monsoon_burst", "Monsoon burst"],
  ["heat_wave", "Heat wave"],
  ["cloud_disconnection", "Cloud disconnection"],
  ["fog_failure", "Fog server failure"],
];

const ALGORITHMS: { group: string; items: [string, string][] }[] = [
  {
    group: "AURA and its ablations",
    items: [
      ["aura", "AURA (proposed)"],
      ["aura_noaoi", "without AoI"],
      ["aura_noreserve", "without reservation"],
      ["aura_staticreserve", "with static reservation"],
      ["aura_noreliability", "without reliability"],
      ["aura_singletier", "single tier"],
    ],
  },
  {
    group: "Baselines",
    items: [
      ["mct", "MCT"],
      ["mct@aura", "MCT with AURA's queue"],
      ["edge_ward", "Edge-ward"],
      ["cloud_only", "Cloud-only"],
      ["least_loaded", "Least loaded"],
      ["round_robin", "Round Robin"],
      ["min_min", "Min-Min (batch)"],
      ["nsga2", "NSGA-II (batch)"],
      ["dqn", "DQN (learned, slow: trains per scenario)"],
    ],
  },
];

const DEFAULT_ALGS = ["aura", "aura_noaoi", "aura_noreserve", "aura_staticreserve", "aura_noreliability", "aura_singletier",
  "mct", "mct@aura", "edge_ward", "cloud_only", "least_loaded", "min_min", "nsga2"];

export default function Evaluation() {
  const [search, setSearch] = useSearchParams();
  const { data: jobs } = useJobs();
  const start = useStartJob();
  const [scenarios, setScenarios] = useState(SCENARIOS.map(([k]) => k));
  const [algs, setAlgs] = useState(DEFAULT_ALGS);
  const [nums, setNums] = useState({ replications: 5, duration_s: 1800, intensity: 100, base_seed: 1 });
  const mine = (jobs ?? []).filter((j) => j.plugin_id === PLUGIN);
  const jobId = search.get("job") ?? mine[0]?.id ?? "";
  const { data: job } = useJob(jobId);
  const { data: result } = useJobResult(jobId, job?.status === "succeeded" && !!job.has_result);
  const active = job?.status === "running" || job?.status === "queued";
  const runs = scenarios.length * algs.length * nums.replications;
  const toggle = (list: string[], set: (v: string[]) => void, key: string, order: string[]) =>
    set(list.includes(key) ? list.filter((x) => x !== key) : order.filter((x) => x === key || list.includes(x)));
  const allAlgKeys = ALGORITHMS.flatMap((g) => g.items.map(([k]) => k));
  const go = () =>
    start.mutate({ plugin_id: PLUGIN, params: { scenarios, algorithms: algs, ...nums } }, { onSuccess: (j) => setSearch({ job: j.id }) });

  return (
    <div>
      <PageHeader
        title="Performance evaluation"
        lead="Evaluate AURA against its ablations and the baselines on every stress scenario, with identical workloads, significance tests and a check of hypotheses H1 to H4."
      />
      <div className="grid gap-10 lg:grid-cols-[20rem_1fr]">
        <aside className="space-y-6">
          <section className="rounded-xl border border-line bg-surface p-5">
            <h2 className="font-semibold">New evaluation</h2>
            <fieldset className="mt-4">
              <legend className="text-xs text-ink-3">Scenarios</legend>
              <div className="mt-2 space-y-1.5">
                {SCENARIOS.map(([k, n]) => (
                  <label key={k} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={scenarios.includes(k)} onChange={() => toggle(scenarios, setScenarios, k, SCENARIOS.map(([x]) => x))} />
                    {n}
                  </label>
                ))}
              </div>
            </fieldset>
            {ALGORITHMS.map((g) => (
              <fieldset key={g.group} className="mt-5">
                <legend className="text-xs text-ink-3">{g.group}</legend>
                <div className="mt-2 space-y-1.5">
                  {g.items.map(([k, n]) => (
                    <label key={k} className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={algs.includes(k)} disabled={k === "aura"}
                        onChange={() => toggle(algs, setAlgs, k, allAlgKeys)} />
                      {n}
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
            <div className="mt-5 grid grid-cols-2 gap-3">
              {([["replications", "Workloads per scenario", "30 for a paper"], ["duration_s", "Simulated time (s)", ""],
                ["intensity", "Workload intensity", "100 = busy season"], ["base_seed", "Seed", ""]] as const).map(([k, l, hint]) => (
                <label key={k} className="block text-sm">
                  <span className="mb-1 block text-xs text-ink-3">{l}</span>
                  <input type="number" value={nums[k]} onChange={(e) => setNums((n) => ({ ...n, [k]: Number(e.target.value) }))}
                    className="w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm" />
                  {hint && <span className="mt-0.5 block text-[11px] text-ink-3">{hint}</span>}
                </label>
              ))}
            </div>
            {start.error && <p className="mt-3 text-sm text-danger">{start.error.message}</p>}
            <Button variant="primary" className="mt-5 w-full" disabled={start.isPending || active || scenarios.length === 0 || algs.length < 2} onClick={go}>
              {active ? "Evaluation running…" : `Run evaluation (${runs.toLocaleString()} simulations)`}
            </Button>
            <p className="mt-2 text-[11px] text-ink-3">
              The defaults take roughly 30–60 minutes on a laptop. For 30 workloads, run it overnight from the command line (see
              docs/aura.md).
            </p>
          </section>
          <p className="text-xs text-ink-3">
            The algorithm is described on its <Link to="/algorithms/scheduler:aura" className="text-accent hover:underline">catalogue page</Link>;
            the scenarios in docs/scenarios.md.
          </p>
        </aside>
        <section className="min-w-0">
          {mine.length > 1 && (
            <label className="mb-6 flex items-center gap-2 text-sm text-ink-2">
              Evaluation
              <select value={jobId} onChange={(e) => setSearch({ job: e.target.value })} className="rounded-lg border border-line bg-surface px-2 py-1 text-sm">
                {mine.map((j) => (
                  <option key={j.id} value={j.id}>{formatTime(j.created_at)}, {j.status}</option>
                ))}
              </select>
            </label>
          )}
          {!jobId && (
            <div className="rounded-xl border border-dashed border-line p-8">
              <h2 className="font-semibold">No evaluation yet</h2>
              <p className="mt-1 max-w-xl text-sm text-ink-2">
                Choose scenarios and algorithms, then run. Results appear here with hypothesis verdicts, per-scenario tables and
                charts, AURA's reservation timeline and sample decisions.
              </p>
            </div>
          )}
          {job && active && (
            <div className="max-w-xl">
              <ProgressBar value={job.progress} status={job.status} />
              <p className="mt-2 text-sm text-ink-2">{job.message}</p>
            </div>
          )}
          {job?.error ? <p className="text-sm text-danger">{String(job.error)}</p> : null}
          {result ? <AuraEvaluationView result={result as AuraEvaluationResult} /> : null}
        </section>
      </div>
    </div>
  );
}
