import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useJob, useJobResult, useJobs, useStartJob } from "@/api/hooks";
import { Button } from "@/components/Button";
import {
  type DQNTrainingResult,
  DQNTrainingView,
  OPT_COLORS,
  type OptimizerBenchmarkResult,
  OptimizerBenchmarkView,
} from "@/components/OptimizationResults";
import { PageHeader } from "@/components/PageHeader";
import { ProgressBar } from "@/components/ProgressBar";
import { cn } from "@/lib/cn";
import { formatTime } from "@/lib/format";

const PLUGIN = "simulation:optimizer_benchmark";

const OPTIMISERS: [string, string, string][] = [
  ["ga", "Genetic Algorithm", "Tournament selection, uniform crossover, mutation, two elites."],
  ["pso", "Particle Swarm Optimisation", "Particles on random keys, inertia falling from 0.9 to 0.4."],
  ["aco", "Ant Colony Optimisation", "MAX-MIN ant system with a speed heuristic per node."],
  ["gwo", "Grey Wolf Optimizer", "Moves toward the three best mappings as exploration shrinks."],
  ["woa", "Whale Optimization Algorithm", "Encircling, random search and spiral moves around the best."],
  ["nsga2", "NSGA-II", "Pareto front over misses, response, energy and cost."],
  ["random_search", "Random search", "Same budget, no learning. Every optimiser should beat it."],
];

type Form = {
  farms: number;
  intensity: number;
  window_s: number;
  duration_s: number;
  algorithms: string[];
  budget: number;
  pop_size: number;
  instances: number;
  replications: number;
  seed_heuristics: boolean;
  base_seed: number;
};

const DEFAULTS: Form = {
  farms: 4,
  intensity: 20,
  window_s: 5,
  duration_s: 3600,
  algorithms: OPTIMISERS.map(([k]) => k),
  budget: 1000,
  pop_size: 20,
  instances: 6,
  replications: 10,
  seed_heuristics: true,
  base_seed: 1,
};

function BenchmarkPanel() {
  const [search, setSearch] = useSearchParams();
  const { data: jobs } = useJobs();
  const start = useStartJob();
  const [form, setForm] = useState(DEFAULTS);
  const mine = (jobs ?? []).filter((j) => j.plugin_id === PLUGIN);
  const latestDone = mine.find((j) => j.status === "succeeded");
  const jobId = search.get("job") ?? mine[0]?.id ?? "";
  const { data: job } = useJob(jobId);
  const { data: result } = useJobResult(jobId, job?.status === "succeeded" && !!job.has_result);
  const active = job?.status === "running" || job?.status === "queued";

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));
  const runs = form.instances * form.replications * form.algorithms.length;
  const go = () =>
    start.mutate({ plugin_id: PLUGIN, params: { ...form } }, { onSuccess: (j) => setSearch({ job: j.id }) });

  const num = (label: string, k: keyof Form, step = "any", hint?: string) => (
    <label className="block text-sm">
      <span className="mb-1 block text-xs text-ink-3">{label}</span>
      <input type="number" step={step} value={form[k] as number} onChange={(e) => set(k, Number(e.target.value) as never)}
        className="w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm" />
      {hint && <span className="mt-0.5 block text-[11px] text-ink-3">{hint}</span>}
    </label>
  );

  return (
    <div>
      <div className="grid gap-10 lg:grid-cols-[20rem_1fr]">
        <aside className="space-y-6">
          <section className="rounded-xl border border-line bg-surface p-5">
            <h2 className="font-semibold">New benchmark</h2>
            <div className="mt-4 grid grid-cols-2 gap-3">
              {num("Farms", "farms", "1")}
              {num("Workload intensity", "intensity")}
              {num("Batch window (s)", "window_s")}
              {num("Simulated time (s)", "duration_s", "60")}
            </div>
            <fieldset className="mt-5">
              <legend className="text-xs text-ink-3">Optimisers</legend>
              <div className="mt-2 space-y-1.5">
                {OPTIMISERS.map(([k, name]) => (
                  <label key={k} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.algorithms.includes(k)}
                      onChange={(e) => set("algorithms", e.target.checked ? OPTIMISERS.map(([x]) => x).filter((x) => x === k || form.algorithms.includes(x)) : form.algorithms.filter((x) => x !== k))} />
                    <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: OPT_COLORS[k] }} aria-hidden />
                    {name}
                  </label>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-ink-3">Min-Min and greedy MCT are always included as reference points.</p>
            </fieldset>
            <div className="mt-5 grid grid-cols-2 gap-3">
              {num("Evaluation budget", "budget", "10", "Same for every optimiser")}
              {num("Population", "pop_size", "1")}
              {num("Windows", "instances", "1")}
              {num("Runs per window", "replications", "1", "30 for a paper")}
              {num("Seed", "base_seed", "1")}
            </div>
            <label className="mt-4 flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={form.seed_heuristics} onChange={(e) => set("seed_heuristics", e.target.checked)} />
              <span>
                Start from Min-Min and greedy MCT
                <span className="block text-[11px] text-ink-3">Off: random starting populations, to judge the search itself.</span>
              </span>
            </label>
            {start.error && <p className="mt-3 text-sm text-danger">{start.error.message}</p>}
            <Button variant="primary" className="mt-5 w-full" disabled={start.isPending || active || form.algorithms.length === 0} onClick={go}>
              {active ? "Benchmark running…" : `Run benchmark (${runs.toLocaleString()} runs)`}
            </Button>
          </section>

          <section>
            <h2 className="font-semibold">The optimisers</h2>
            <ul className="mt-3 space-y-3 text-sm">
              {OPTIMISERS.map(([k, name, what]) => (
                <li key={k}>
                  <Link to={`/algorithms/optimizer:${k}`} className="font-medium hover:text-accent">{name}</Link>
                  <span className="block text-xs text-ink-3">{what}</span>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-xs text-ink-3">
              Each one is also a batch placement policy. To measure deadlines, energy and cost end to end, choose them in{" "}
              <Link to="/experiments" className="text-accent hover:underline">Experiments</Link>.
            </p>
          </section>
        </aside>

        <section className="min-w-0">
          {mine.length > 1 && (
            <label className="mb-6 flex items-center gap-2 text-sm text-ink-2">
              Benchmark
              <select value={jobId} onChange={(e) => setSearch({ job: e.target.value })}
                className="rounded-lg border border-line bg-surface px-2 py-1 text-sm">
                {mine.map((j) => (
                  <option key={j.id} value={j.id}>
                    {formatTime(j.created_at)}, {j.status}
                  </option>
                ))}
              </select>
            </label>
          )}
          {!jobId && (
            <div className="rounded-xl border border-dashed border-line p-8">
              <h2 className="font-semibold">No benchmark yet</h2>
              <p className="mt-1 max-w-xl text-sm text-ink-2">
                Run one with the defaults: it simulates an hour of farm traffic, freezes six scheduling windows and gives every
                optimiser ten seeded runs on each. It takes about a minute on a laptop.
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
          {result ? <OptimizerBenchmarkView result={result as OptimizerBenchmarkResult} /> : null}
          {job && !active && result === undefined && latestDone && latestDone.id !== jobId && (
            <button className="text-sm text-accent hover:underline" onClick={() => setSearch({ job: latestDone.id })}>
              Show the last finished benchmark
            </button>
          )}
        </section>
      </div>
    </div>
  );
}

const DQN_PLUGIN = "simulation:dqn_training";

type DQNForm = {
  farms: number;
  intensity: number;
  duration_s: number;
  episodes: number;
  episode_s: number;
  gamma: number;
  lambda_energy: number;
  lambda_cost: number;
  evaluation_replications: number;
  base_seed: number;
};

const DQN_DEFAULTS: DQNForm = {
  farms: 4,
  intensity: 20,
  duration_s: 3600,
  episodes: 30,
  episode_s: 600,
  gamma: 0.5,
  lambda_energy: 0.1,
  lambda_cost: 0.1,
  evaluation_replications: 10,
  base_seed: 1,
};

function DQNPanel() {
  const [search, setSearch] = useSearchParams();
  const { data: jobs } = useJobs();
  const start = useStartJob();
  const [form, setForm] = useState(DQN_DEFAULTS);
  const mine = (jobs ?? []).filter((j) => j.plugin_id === DQN_PLUGIN);
  const jobId = search.get("job") ?? mine[0]?.id ?? "";
  const { data: job } = useJob(jobId);
  const { data: result } = useJobResult(jobId, job?.status === "succeeded" && !!job.has_result);
  const active = job?.status === "running" || job?.status === "queued";
  const go = () =>
    start.mutate({ plugin_id: DQN_PLUGIN, params: { ...form } }, { onSuccess: (j) => setSearch({ tab: "dqn", job: j.id }) });
  const num = (label: string, k: keyof DQNForm, step = "any", hint?: string) => (
    <label className="block text-sm">
      <span className="mb-1 block text-xs text-ink-3">{label}</span>
      <input type="number" step={step} value={form[k]} onChange={(e) => setForm((f) => ({ ...f, [k]: Number(e.target.value) }))}
        className="w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm" />
      {hint && <span className="mt-0.5 block text-[11px] text-ink-3">{hint}</span>}
    </label>
  );

  return (
    <div className="grid gap-10 lg:grid-cols-[20rem_1fr]">
      <aside className="space-y-6">
        <section className="rounded-xl border border-line bg-surface p-5">
          <h2 className="font-semibold">Train and evaluate</h2>
          <p className="mt-1 text-xs text-ink-3">
            The DQN learns to place each task as it arrives. It trains on fresh simulated workloads, then is tested against MCT,
            edge-ward, least-loaded and random placement on workloads it has never seen.
          </p>
          <div className="mt-4 grid grid-cols-2 gap-3">
            {num("Farms", "farms", "1")}
            {num("Workload intensity", "intensity")}
            {num("Training episodes", "episodes", "1")}
            {num("Episode length (s)", "episode_s", "60", "Under heavy load, as long as the test")}
            {num("Discount (gamma)", "gamma", "0.05")}
            {num("Energy penalty", "lambda_energy", "0.05")}
            {num("Cost penalty", "lambda_cost", "0.05")}
            {num("Test length (s)", "duration_s", "60")}
            {num("Test workloads", "evaluation_replications", "1", "30 for a paper")}
            {num("Seed", "base_seed", "1")}
          </div>
          {start.error && <p className="mt-3 text-sm text-danger">{start.error.message}</p>}
          <Button variant="primary" className="mt-5 w-full" disabled={start.isPending || active} onClick={go}>
            {active ? "Training…" : "Train and evaluate"}
          </Button>
        </section>
        <p className="text-xs text-ink-3">
          The trained policy is also the <Link to="/algorithms/placement:dqn" className="text-accent hover:underline">DQN placement</Link>,
          which you can choose in Experiments. It trains once per network and settings, then reuses what it learned.
        </p>
      </aside>
      <section className="min-w-0">
        {mine.length > 1 && (
          <label className="mb-6 flex items-center gap-2 text-sm text-ink-2">
            Training run
            <select value={jobId} onChange={(e) => setSearch({ tab: "dqn", job: e.target.value })}
              className="rounded-lg border border-line bg-surface px-2 py-1 text-sm">
              {mine.map((j) => (
                <option key={j.id} value={j.id}>{formatTime(j.created_at)}, {j.status}</option>
              ))}
            </select>
          </label>
        )}
        {!jobId && (
          <div className="rounded-xl border border-dashed border-line p-8">
            <h2 className="font-semibold">No training run yet</h2>
            <p className="mt-1 max-w-xl text-sm text-ink-2">
              With the defaults it trains for 30 short episodes and tests on 10 one-hour workloads. It takes about one to three
              minutes on a laptop and needs no graphics card.
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
        {result ? <DQNTrainingView result={result as DQNTrainingResult} /> : null}
      </section>
    </div>
  );
}

export default function Optimization() {
  const [search, setSearch] = useSearchParams();
  const tab = search.get("tab") === "dqn" ? "dqn" : "benchmark";
  const tabs: [string, string][] = [
    ["benchmark", "Metaheuristic benchmark"],
    ["dqn", "Learned scheduler (DQN)"],
  ];
  return (
    <div>
      <PageHeader
        title="Optimization lab"
        lead="Compare metaheuristic and learned schedulers on identical simulated workloads, with equal budgets and held-out tests."
      />
      <div className="mb-8 flex gap-1 border-b border-line" role="tablist">
        {tabs.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setSearch(k === "dqn" ? { tab: k } : {})}
            className={cn("-mb-px border-b-2 px-3 py-2 text-sm", tab === k ? "border-accent text-ink" : "border-transparent text-ink-2 hover:text-ink")}>
            {label}
          </button>
        ))}
      </div>
      {tab === "dqn" ? <DQNPanel /> : <BenchmarkPanel />}
    </div>
  );
}
