import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { ExperimentSchema } from "@/api/client";
import {
  fetchTopology,
  fetchWorkload,
  useCancelExperiment,
  useCreateExperiment,
  useDeleteExperiment,
  useDuplicateExperiment,
  useExperiment,
  useExperimentResult,
  useExperimentSchema,
  useRunExperiment,
  useTopologies,
  useUpdateExperiment,
  useWorkloads,
} from "@/api/hooks";
import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { type ExperimentResult, ExperimentResults } from "@/components/ExperimentResults";
import { ProgressBar } from "@/components/ProgressBar";
import { type JsonSchema, SchemaForm } from "@/components/SchemaForm";
import { formatTime } from "@/lib/format";
import { useUi } from "@/stores/ui";

type Algorithm = { label?: string | null; placement: string; discipline: string; placement_params?: Record<string, unknown> };
type Spec = {
  name: string;
  description: string;
  objective: string;
  scenario: Record<string, unknown>;
  algorithms: Algorithm[];
  replications: number;
  base_seed: number;
  topology?: Record<string, unknown> | null;
  workload?: Record<string, unknown> | null;
  topology_name?: string;
  workload_name?: string;
  [k: string]: unknown;
};

export default function ExperimentPage() {
  const { expId } = useParams();
  const isNew = !expId;
  const { data: schema } = useExperimentSchema();
  const { data: exp, isLoading } = useExperiment(expId ?? "");

  if (!schema || (!isNew && isLoading)) return <p className="text-sm text-ink-3">Loading…</p>;
  if (!isNew && !exp) return <p className="text-sm text-danger">Experiment not found.</p>;

  if (isNew || exp?.status === "draft") {
    return <Editor key={expId ?? "new"} schema={schema} initial={(exp?.spec ?? schema.default_spec) as Spec} expId={expId} />;
  }
  return <Detail expId={expId!} />;
}

function Editor({ schema, initial, expId }: { schema: ExperimentSchema; initial: Spec; expId?: string }) {
  const navigate = useNavigate();
  const mode = useUi((s) => s.mode);
  const projectId = useUi((s) => s.currentProjectId);
  const [spec, setSpec] = useState<Spec>(initial);
  const create = useCreateExperiment();
  const update = useUpdateExperiment();
  const run = useRunExperiment();
  const del = useDeleteExperiment();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const error = create.error ?? update.error ?? run.error;
  const busy = create.isPending || update.isPending || run.isPending;

  const set = (patch: Partial<Spec>) => setSpec((s) => ({ ...s, ...patch }));
  const setAlg = (i: number, patch: Partial<Algorithm>) =>
    set({ algorithms: spec.algorithms.map((a, j) => (j === i ? { ...a, ...patch } : a)) });
  const labelOf = (a: Algorithm) => a.label || `${a.placement}/${a.discipline}`;
  const labels = spec.algorithms.map(labelOf);
  const duplicates = labels.length !== new Set(labels).size;

  const save = async (andRun: boolean) => {
    const saved = expId ? await update.mutateAsync({ id: expId, spec }) : await create.mutateAsync({ spec, project_id: projectId });
    if (andRun) await run.mutateAsync(saved.id);
    navigate(`/experiments/${saved.id}`, { replace: true });
  };

  return (
    <article className="max-w-4xl">
      <Link to="/experiments" className="text-sm text-ink-3 hover:text-accent">Experiments</Link>
      <h1 className="mt-2 text-[1.65rem] font-semibold tracking-[-0.01em]">{expId ? "Edit experiment" : "New experiment"}</h1>
      <p className="mt-2 max-w-2xl text-ink-2">
        Once an experiment has run, its definition is frozen so the results stay reproducible. To change it afterwards,
        duplicate it.
      </p>

      <Section title="What you're testing">
        <div className="grid gap-5">
          <Text label="Name" value={spec.name} onChange={(name) => set({ name })} required />
          <Text label="Research question or hypothesis" value={spec.objective} onChange={(objective) => set({ objective })} multiline
            placeholder="e.g. Does edge-ward placement meet more urgent deadlines than cloud-only on a slow rural link?" />
          <Text label="Notes" value={spec.description} onChange={(description) => set({ description })} multiline />
        </div>
      </Section>

      <Section title="Scenario" lead="The farm network and workload every algorithm is tested on.">
        <ScenarioSource spec={spec} set={set} />
        {spec.topology ? (
          <SchemaForm schema={onlyFields(schema.scenario_schema as JsonSchema, ["window_s"])} values={spec.scenario}
            onChange={(scenario) => set({ scenario })} showAdvanced />
        ) : (
          <SchemaForm schema={schema.scenario_schema as JsonSchema} values={spec.scenario} onChange={(scenario) => set({ scenario })}
            showAdvanced={mode === "researcher"} />
        )}
      </Section>

      <Section title="Algorithms to compare" lead="Each algorithm is a placement policy (which node runs a task) plus a queue discipline (in what order a node runs its tasks).">
        <ul className="space-y-3">
          {spec.algorithms.map((a, i) => (
            <li key={i} className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_12rem_auto]">
              <Select label={i === 0 ? "Placement" : undefined} ariaLabel={`Placement ${i + 1}`} value={a.placement}
                options={schema.placements} onChange={(placement) => setAlg(i, { placement })} />
              <Select label={i === 0 ? "Queue discipline" : undefined} ariaLabel={`Queue discipline ${i + 1}`} value={a.discipline}
                options={schema.disciplines} onChange={(discipline) => setAlg(i, { discipline })} />
              <label className="text-sm">
                {i === 0 && <span className="mb-1.5 block font-medium">Label in results</span>}
                <input value={a.label ?? ""} placeholder={`${a.placement}/${a.discipline}`} aria-label={`Label ${i + 1}`}
                  onChange={(e) => setAlg(i, { label: e.target.value || null })}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2" />
              </label>
              <Button variant="ghost" aria-label={`Remove algorithm ${i + 1}`} disabled={spec.algorithms.length <= 2}
                onClick={() => set({ algorithms: spec.algorithms.filter((_, j) => j !== i) })}>
                <X className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
        <Button className="mt-4" onClick={() => set({ algorithms: [...spec.algorithms, { placement: "least_loaded", discipline: "edf" }] })}>
          <Plus className="size-4" /> Add algorithm
        </Button>
        {duplicates && <p className="mt-3 text-sm text-danger">Two algorithms have the same label. Give one of them a different label.</p>}
      </Section>

      <Section title="Replications">
        <div className="grid gap-5 sm:grid-cols-2">
          <label className="text-sm">
            <span className="mb-1.5 block font-medium">Replications per algorithm</span>
            <input type="number" min={2} max={500} value={spec.replications}
              onChange={(e) => set({ replications: Number(e.target.value) })}
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 tabular-nums" />
            <span className="mt-1 block text-xs text-ink-3">30 is the usual minimum for papers. With fewer than 10, pairwise tests rarely reach significance.</span>
          </label>
          <label className="text-sm">
            <span className="mb-1.5 block font-medium">First seed</span>
            <input type="number" min={0} value={spec.base_seed} onChange={(e) => set({ base_seed: Number(e.target.value) })}
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 tabular-nums" />
            <span className="mt-1 block text-xs text-ink-3">Replication r uses seed (first seed + r). Same seeds, same results.</span>
          </label>
        </div>
        <p className="mt-4 text-sm text-ink-2">
          This experiment will simulate <span className="font-medium tabular-nums">{spec.algorithms.length * spec.replications}</span> runs.
        </p>
      </Section>

      {error && <p className="mt-6 text-sm text-danger">{error.message}</p>}
      <div className="mt-8 flex flex-wrap gap-2 border-t border-line pt-6">
        <Button variant="primary" disabled={busy || duplicates || !spec.name.trim()} onClick={() => void save(true)}>
          Save and run
        </Button>
        <Button disabled={busy || duplicates || !spec.name.trim()} onClick={() => void save(false)}>
          Save draft
        </Button>
        {expId && (
          <Button variant="ghost" className="ml-auto" onClick={() => setConfirmDelete(true)}>
            Delete draft
          </Button>
        )}
      </div>
      <ConfirmDialog open={confirmDelete} title="Delete this draft?" body="The experiment definition is removed. This can't be undone."
        confirmLabel="Delete draft" onCancel={() => setConfirmDelete(false)}
        onConfirm={() => expId && del.mutate(expId, { onSuccess: () => navigate("/experiments") })} />
    </article>
  );
}

function Detail({ expId }: { expId: string }) {
  const navigate = useNavigate();
  const { data: exp } = useExperiment(expId);
  const finished = exp?.status === "succeeded" && exp.has_result;
  const { data: result } = useExperimentResult(expId, Boolean(finished), exp?.job_id);
  const run = useRunExperiment();
  const cancel = useCancelExperiment();
  const duplicate = useDuplicateExperiment();
  const del = useDeleteExperiment();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [elapsedTick, setTick] = useState(0);

  const active = exp?.status === "running" || exp?.status === "queued";
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, [active]);
  void elapsedTick;

  if (!exp) return null;
  const spec = exp.spec as Spec;

  return (
    <article>
      <Link to="/experiments" className="text-sm text-ink-3 hover:text-accent">Experiments</Link>
      <header className="mt-2 mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <h1 className="text-[1.65rem] font-semibold tracking-[-0.01em]">{exp.name}</h1>
          {exp.objective && <p className="mt-2 text-ink-2">{exp.objective}</p>}
          <p className="mt-2 text-sm text-ink-3">
            {exp.algorithms.join(", ")}. {spec.replications} replications, {exp.total_runs} runs. Created {formatTime(exp.created_at)}.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {active ? (
            <Button onClick={() => cancel.mutate(expId)} disabled={cancel.isPending}>Cancel run</Button>
          ) : (
            <Button onClick={() => run.mutate(expId)} disabled={run.isPending} title="Re-running gives identical results, which checks reproducibility">
              Run again
            </Button>
          )}
          <Button onClick={() => duplicate.mutate(expId, { onSuccess: (copy) => navigate(`/experiments/${copy.id}`) })}>Duplicate to edit</Button>
          {!active && <Button variant="ghost" onClick={() => setConfirmDelete(true)}>Delete</Button>}
        </div>
      </header>

      {active && (
        <div className="max-w-xl">
          <ProgressBar value={exp.progress} status={exp.status} />
          <p className="mt-2 text-sm text-ink-2">{exp.message}</p>
        </div>
      )}
      {(exp.status === "failed" || exp.status === "interrupted") && <p className="text-sm text-danger">{exp.message}</p>}
      {exp.status === "cancelled" && <p className="text-sm text-ink-2">This run was cancelled. Run it again to get results.</p>}

      {result ? <ExperimentResults result={result as unknown as ExperimentResult} exportBase={`/api/experiments/${expId}/export`} /> : null}

      <details className="mt-10 text-sm">
        <summary className="cursor-pointer text-ink-2">Scenario settings</summary>
        <pre className="mt-2 overflow-x-auto rounded-lg border border-line bg-surface p-3 text-xs">{JSON.stringify(spec.scenario, null, 2)}</pre>
      </details>

      <ConfirmDialog open={confirmDelete} title={`Delete "${exp.name}"?`}
        body="The experiment definition is removed. Its result files stay in your results folder. This can't be undone."
        confirmLabel="Delete experiment" onCancel={() => setConfirmDelete(false)}
        onConfirm={() => del.mutate(expId, { onSuccess: () => navigate("/experiments") })} />
    </article>
  );
}

function onlyFields(schema: JsonSchema, keep: string[]): JsonSchema {
  return { ...schema, properties: Object.fromEntries(Object.entries(schema.properties ?? {}).filter(([k]) => keep.includes(k))) };
}

/** Choose between the generated farm network and a saved topology + workload (copied into the experiment). */
function ScenarioSource({ spec, set }: { spec: Spec; set: (p: Partial<Spec>) => void }) {
  const { data: topologies } = useTopologies();
  const { data: workloads } = useWorkloads();
  const [busy, setBusy] = useState(false);
  const saved = Boolean(spec.topology);
  const canUseSaved = Boolean(topologies?.length && workloads?.length);

  const choose = async (topologyId: string | undefined, workloadId: string | undefined) => {
    if (!topologyId || !workloadId) return;
    setBusy(true);
    try {
      const [t, w] = await Promise.all([fetchTopology(topologyId), fetchWorkload(workloadId)]);
      set({ topology: t.topology, workload: w.spec, topology_name: t.name, workload_name: w.name });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mb-6 space-y-3 text-sm">
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Scenario source">
        {[
          { key: false, label: "Generated farm network" },
          { key: true, label: "My saved network and workload" },
        ].map((o) => (
          <button key={String(o.key)} type="button" role="radio" aria-checked={saved === o.key}
            disabled={o.key && !canUseSaved}
            onClick={() => (o.key ? void choose(topologies?.[0]?.id, workloads?.[0]?.id) : set({ topology: null, workload: null, topology_name: "", workload_name: "" }))}
            className={`rounded-lg border px-3 py-1.5 ${saved === o.key ? "border-accent bg-accent-soft font-medium text-accent" : "border-line bg-surface hover:bg-surface-2"} disabled:opacity-50`}>
            {o.label}
          </button>
        ))}
      </div>
      {!canUseSaved && <p className="text-xs text-ink-3">Save a topology (Topology designer) and a workload (Simulation) to use your own network.</p>}
      {saved && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label><span className="mb-1.5 block font-medium">Topology</span>
            <select disabled={busy} className="w-full rounded-lg border border-line bg-surface px-3 py-2"
              value={topologies?.find((t) => t.name === spec.topology_name)?.id ?? ""}
              onChange={(e) => void choose(e.target.value, workloads?.find((w) => w.name === spec.workload_name)?.id ?? workloads?.[0]?.id)}>
              {!topologies?.some((t) => t.name === spec.topology_name) && <option value="">{spec.topology_name || "Choose"} (copy in this experiment)</option>}
              {topologies?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          <label><span className="mb-1.5 block font-medium">Workload</span>
            <select disabled={busy} className="w-full rounded-lg border border-line bg-surface px-3 py-2"
              value={workloads?.find((w) => w.name === spec.workload_name)?.id ?? ""}
              onChange={(e) => void choose(topologies?.find((t) => t.name === spec.topology_name)?.id ?? topologies?.[0]?.id, e.target.value)}>
              {!workloads?.some((w) => w.name === spec.workload_name) && <option value="">{spec.workload_name || "Choose"} (copy in this experiment)</option>}
              {workloads?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </label>
          <p className="text-xs text-ink-3 sm:col-span-2">
            The experiment stores its own copy of both, so later edits to the saved versions won't change its results.
          </p>
        </div>
      )}
    </div>
  );
}

function Section({ title, lead, children }: { title: string; lead?: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold">{title}</h2>
      {lead && <p className="mt-1 text-sm text-ink-2">{lead}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Text({ label, value, onChange, multiline, required, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; multiline?: boolean; required?: boolean; placeholder?: string;
}) {
  const cls = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm";
  return (
    <label className="block text-sm">
      <span className="mb-1.5 block font-medium">{label}</span>
      {multiline ? (
        <textarea rows={2} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className={cls} />
      ) : (
        <input value={value} required={required} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className={cls} />
      )}
    </label>
  );
}

function Select({ label, ariaLabel, value, options, onChange }: {
  label?: string; ariaLabel: string; value: string; options: { key: string; name: string; summary: string }[]; onChange: (v: string) => void;
}) {
  return (
    <label className="text-sm">
      {label && <span className="mb-1.5 block font-medium">{label}</span>}
      <select aria-label={ariaLabel} value={value} onChange={(e) => onChange(e.target.value)}
        title={options.find((o) => o.key === value)?.summary}
        className="w-full rounded-lg border border-line bg-surface px-3 py-2">
        {options.map((o) => (
          <option key={o.key} value={o.key}>{o.name}</option>
        ))}
      </select>
    </label>
  );
}
