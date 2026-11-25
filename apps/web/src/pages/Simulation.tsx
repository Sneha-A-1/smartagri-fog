import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useDeleteWorkload, useExperimentSchema, useStartSimulation, useTopologies, useWorkloads } from "@/api/hooks";
import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { formatTime } from "@/lib/format";
import { useUi } from "@/stores/ui";

export default function Simulation() {
  const navigate = useNavigate();
  const projectId = useUi((s) => s.currentProjectId);
  const mode = useUi((s) => s.mode);
  const { data: topologies } = useTopologies();
  const { data: workloads } = useWorkloads();
  const { data: schema } = useExperimentSchema();
  const start = useStartSimulation();
  const del = useDeleteWorkload();
  const [toDelete, setToDelete] = useState<{ id: string; name: string } | null>(null);
  const [form, setForm] = useState({ topology_id: "", workload_id: "", placement: "mct", discipline: "edf", seed: 1, window_s: 5, failures: true });

  const topologyId = form.topology_id || topologies?.[0]?.id || "";
  const workloadId = form.workload_id || workloads?.[0]?.id || "";
  const ready = Boolean(topologyId && workloadId);

  const run = () =>
    start.mutate(
      { topology_id: topologyId, workload_id: workloadId, placement: form.placement, discipline: form.discipline, seed: form.seed,
        settings: { window_s: form.window_s, failures: form.failures }, project_id: projectId },
      { onSuccess: (job) => navigate(`/jobs/${job.id}`) },
    );

  const select = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm";

  return (
    <>
      <PageHeader title="Simulation" lead="Run one simulation of a saved network and workload to explore how a policy behaves. To compare policies with statistics, use Experiments." />

      <div className="grid gap-12 lg:grid-cols-[1fr_22rem]">
        <section>
          <h2 className="text-lg font-semibold">Run a simulation</h2>
          {!topologies?.length || !workloads?.length ? (
            <p className="mt-2 text-sm text-ink-2">
              You need at least one saved topology and one saved workload.{" "}
              {!topologies?.length && <Link to="/topology/new" className="text-accent hover:underline">Design a topology</Link>}
              {!topologies?.length && !workloads?.length && " and "}
              {!workloads?.length && <Link to="/simulation/workloads/new" className="text-accent hover:underline">create a workload</Link>}.
            </p>
          ) : (
            <div className="mt-4 grid max-w-2xl gap-5 sm:grid-cols-2">
              <label className="text-sm"><span className="mb-1.5 block font-medium">Topology</span>
                <select className={select} value={topologyId} onChange={(e) => setForm({ ...form, topology_id: e.target.value })}>
                  {topologies.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.nodes} nodes)</option>)}
                </select>
              </label>
              <label className="text-sm"><span className="mb-1.5 block font-medium">Workload</span>
                <select className={select} value={workloadId} onChange={(e) => setForm({ ...form, workload_id: e.target.value })}>
                  {workloads.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </label>
              <label className="text-sm"><span className="mb-1.5 block font-medium">Placement policy</span>
                <select className={select} value={form.placement} onChange={(e) => setForm({ ...form, placement: e.target.value })}>
                  {schema?.placements.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
                </select>
              </label>
              <label className="text-sm"><span className="mb-1.5 block font-medium">Queue discipline</span>
                <select className={select} value={form.discipline} onChange={(e) => setForm({ ...form, discipline: e.target.value })}>
                  {schema?.disciplines.map((d) => <option key={d.key} value={d.key}>{d.name}</option>)}
                </select>
              </label>
              <label className="text-sm"><span className="mb-1.5 block font-medium">Seed</span>
                <input type="number" min={0} className={select} value={form.seed} onChange={(e) => setForm({ ...form, seed: Number(e.target.value) })} />
              </label>
              {mode === "researcher" && (
                <>
                  <label className="text-sm"><span className="mb-1.5 flex justify-between font-medium">Batch window<span className="font-normal text-ink-3">s</span></span>
                    <input type="number" min={0.1} step="any" className={select} value={form.window_s} onChange={(e) => setForm({ ...form, window_s: Number(e.target.value) })} />
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.failures} onChange={(e) => setForm({ ...form, failures: e.target.checked })} className="size-4 accent-[var(--accent)]" />
                    Apply node failure rates from the topology
                  </label>
                </>
              )}
              <div className="sm:col-span-2">
                {start.error && <p className="mb-3 text-sm text-danger">{start.error.message}</p>}
                <Button variant="primary" onClick={run} disabled={!ready || start.isPending}>Run simulation</Button>
              </div>
            </div>
          )}
        </section>

        <section>
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-semibold">Workloads</h2>
            <Link to="/simulation/workloads/new" className="text-sm text-accent hover:underline">New workload</Link>
          </div>
          {workloads?.length === 0 && <p className="mt-2 text-sm text-ink-2">No workloads yet. The new-workload page starts from the agricultural task mix.</p>}
          <ul className="mt-3 divide-y divide-line border-y border-line text-sm">
            {workloads?.map((w) => (
              <li key={w.id} className="flex items-center gap-3 py-2.5">
                <Link to={`/simulation/workloads/${w.id}`} className="min-w-0 flex-1 hover:text-accent">
                  <div className="font-medium">{w.name}</div>
                  <div className="text-xs text-ink-3">{w.classes} task types, {w.duration_s} s, intensity {w.intensity}. {formatTime(w.updated_at)}</div>
                </Link>
                <Button variant="ghost" onClick={() => setToDelete({ id: w.id, name: w.name })}>Delete</Button>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <ConfirmDialog open={toDelete !== null} title={`Delete "${toDelete?.name}"?`}
        body="The saved workload is removed. Experiments that used it keep their own copy." confirmLabel="Delete workload"
        onCancel={() => setToDelete(null)} onConfirm={() => { if (toDelete) del.mutate(toDelete.id); setToDelete(null); }} />
    </>
  );
}
