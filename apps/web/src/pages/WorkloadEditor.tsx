import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { fetchTopology, previewWorkload, useSaveWorkload, useTopologies, useWorkload, useWorkloadTemplate } from "@/api/hooks";
import { Button } from "@/components/Button";
import { fmt } from "@/components/SimulationResults";

type TaskClass = {
  name: string; category: string; priority: "critical" | "high" | "medium" | "low"; rate_per_source_per_h: number;
  length_mi: number; length_dist: "fixed" | "exponential" | "uniform"; length_spread: number; input_kb: number;
  output_kb: number; ram_mb: number; deadline_s: number; result_to: "source" | "none";
};
type Spec = { name: string; duration_s: number; intensity: number; classes: TaskClass[]; sources?: string[] | null };
type Preview = Awaited<ReturnType<typeof previewWorkload>>;

const COLUMNS: { key: keyof TaskClass; label: string; unit?: string; width: string }[] = [
  { key: "rate_per_source_per_h", label: "Rate", unit: "/gateway/h", width: "w-24" },
  { key: "length_mi", label: "Length", unit: "MI", width: "w-24" },
  { key: "input_kb", label: "Input", unit: "KB", width: "w-20" },
  { key: "output_kb", label: "Output", unit: "KB", width: "w-20" },
  { key: "ram_mb", label: "RAM", unit: "MB", width: "w-20" },
  { key: "deadline_s", label: "Deadline", unit: "s", width: "w-20" },
];

export default function WorkloadEditor() {
  const { wlId } = useParams();
  const { data: template } = useWorkloadTemplate();
  const { data: saved, isLoading } = useWorkload(wlId ?? "");
  if (!template || (wlId && isLoading)) return <p className="text-sm text-ink-3">Loading…</p>;
  if (wlId && !saved) return <p className="text-sm text-danger">Workload not found.</p>;
  const initial = (saved?.spec ?? { ...template.spec, name: "Agricultural task mix" }) as unknown as Spec;
  return <Editor key={wlId ?? "new"} wlId={wlId} initial={initial} initialDescription={saved?.description ?? ""} />;
}

function Editor({ wlId, initial, initialDescription }: { wlId?: string; initial: Spec; initialDescription: string }) {
  const navigate = useNavigate();
  const save = useSaveWorkload();
  const { data: topologies } = useTopologies();
  const [spec, setSpec] = useState<Spec>(initial);
  const [description, setDescription] = useState(initialDescription);
  const [previewTopo, setPreviewTopo] = useState<string>("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const setClass = (i: number, patch: Partial<TaskClass>) =>
    setSpec((s) => ({ ...s, classes: s.classes.map((c, j) => (j === i ? { ...c, ...patch } : c)) }));

  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const topo = previewTopo ? (await fetchTopology(previewTopo)).topology : null;
        setPreview(await previewWorkload(spec as never, topo as never));
        setPreviewError(null);
      } catch (e) {
        setPreviewError((e as Error).message);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [spec, previewTopo]);

  const doSave = () =>
    save.mutate(
      { id: wlId, body: { name: spec.name, description, spec: spec as never } },
      { onSuccess: (row) => (wlId ? undefined : navigate(`/simulation/workloads/${row.id}`, { replace: true })) },
    );

  const load = preview?.load_ratio;

  return (
    <article>
      <Link to="/simulation" className="text-sm text-ink-3 hover:text-accent">Simulation</Link>
      <h1 className="mt-2 text-[1.65rem] font-semibold tracking-[-0.01em]">{wlId ? "Edit workload" : "New workload"}</h1>
      <p className="mt-2 max-w-2xl text-ink-2">
        A workload is the set of agricultural computing tasks your gateways generate. Each task type arrives at random
        (Poisson) at the given rate per gateway, and must finish within its deadline.
      </p>

      <div className="mt-8 grid max-w-3xl gap-5 sm:grid-cols-[1fr_9rem_9rem]">
        <label className="text-sm">
          <span className="mb-1.5 block font-medium">Name</span>
          <input value={spec.name} onChange={(e) => setSpec({ ...spec, name: e.target.value })} className="w-full rounded-lg border border-line bg-surface px-3 py-2" />
        </label>
        <label className="text-sm">
          <span className="mb-1.5 flex justify-between font-medium">Duration<span className="font-normal text-ink-3">s</span></span>
          <input type="number" min={1} value={spec.duration_s} onChange={(e) => setSpec({ ...spec, duration_s: Number(e.target.value) })} className="w-full rounded-lg border border-line bg-surface px-3 py-2 tabular-nums" />
        </label>
        <label className="text-sm">
          <span className="mb-1.5 block font-medium">Intensity</span>
          <input type="number" min={0.01} step="any" value={spec.intensity} onChange={(e) => setSpec({ ...spec, intensity: Number(e.target.value) })} className="w-full rounded-lg border border-line bg-surface px-3 py-2 tabular-nums" />
        </label>
        <label className="text-sm sm:col-span-3">
          <span className="mb-1.5 block font-medium">Description</span>
          <input value={description} onChange={(e) => setDescription(e.target.value)} className="w-full rounded-lg border border-line bg-surface px-3 py-2" />
        </label>
      </div>

      <h2 className="mt-10 text-lg font-semibold">Task types</h2>
      <p className="mt-1 text-sm text-ink-2">
        Default values are placeholders for illustration. Replace lengths and sizes with values measured from real
        implementations before using results in a paper.
      </p>
      <div className="mt-4 overflow-x-auto">
        <table className="text-sm">
          <thead className="text-left text-xs text-ink-3">
            <tr className="border-b border-line">
              <th className="py-2 pr-2 font-normal">Task type</th>
              <th className="py-2 pr-2 font-normal">Priority</th>
              {COLUMNS.map((c) => (
                <th key={c.key} className="py-2 pr-2 font-normal">{c.label}<span className="block">{c.unit}</span></th>
              ))}
              <th className="py-2 pr-2 font-normal">Length varies</th>
              <th className="py-2 pr-2 font-normal">Result to</th>
              <th />
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {spec.classes.map((c, i) => (
              <tr key={i}>
                <td className="py-1.5 pr-2"><input aria-label={`Task type ${i + 1}`} value={c.name} onChange={(e) => setClass(i, { name: e.target.value })} className="w-44 rounded-md border border-line bg-surface px-2 py-1" /></td>
                <td className="py-1.5 pr-2">
                  <select aria-label={`Priority ${i + 1}`} value={c.priority} onChange={(e) => setClass(i, { priority: e.target.value as TaskClass["priority"] })} className="rounded-md border border-line bg-surface px-2 py-1">
                    {["critical", "high", "medium", "low"].map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                </td>
                {COLUMNS.map((col) => (
                  <td key={col.key} className="py-1.5 pr-2">
                    <input type="number" step="any" min={0} aria-label={`${col.label} ${i + 1}`} value={c[col.key] as number}
                      onChange={(e) => setClass(i, { [col.key]: Number(e.target.value) } as Partial<TaskClass>)}
                      className={`${col.width} rounded-md border border-line bg-surface px-2 py-1 tabular-nums`} />
                  </td>
                ))}
                <td className="py-1.5 pr-2">
                  <select aria-label={`Length distribution ${i + 1}`} value={c.length_dist} onChange={(e) => setClass(i, { length_dist: e.target.value as TaskClass["length_dist"] })} className="rounded-md border border-line bg-surface px-2 py-1">
                    <option value="fixed">No</option>
                    <option value="uniform">±{Math.round(c.length_spread * 100)}%</option>
                    <option value="exponential">Exponential</option>
                  </select>
                </td>
                <td className="py-1.5 pr-2">
                  <select aria-label={`Result destination ${i + 1}`} value={c.result_to} onChange={(e) => setClass(i, { result_to: e.target.value as TaskClass["result_to"] })} className="rounded-md border border-line bg-surface px-2 py-1">
                    <option value="source">Gateway</option>
                    <option value="none">Stored only</option>
                  </select>
                </td>
                <td className="py-1.5">
                  <Button variant="ghost" aria-label={`Remove task type ${i + 1}`} disabled={spec.classes.length <= 1}
                    onClick={() => setSpec({ ...spec, classes: spec.classes.filter((_, j) => j !== i) })}><X className="size-4" /></Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button className="mt-3" onClick={() => setSpec({ ...spec, classes: [...spec.classes, {
        name: `task_${spec.classes.length + 1}`, category: "general", priority: "medium", rate_per_source_per_h: 10, length_mi: 1000,
        length_dist: "uniform", length_spread: 0.2, input_kb: 1, output_kb: 0.5, ram_mb: 64, deadline_s: 10, result_to: "source" }] })}>
        <Plus className="size-4" />Add task type
      </Button>

      <section className="mt-10 max-w-3xl rounded-xl border border-line bg-surface p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="font-semibold">Expected load</h2>
          <label className="text-sm">
            <span className="mr-2 text-ink-3">Against topology</span>
            <select value={previewTopo} onChange={(e) => setPreviewTopo(e.target.value)} className="rounded-md border border-line bg-surface px-2 py-1">
              <option value="">One gateway (no topology)</option>
              {topologies?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
        </div>
        {previewError && <p className="mt-2 text-sm text-danger">{previewError}</p>}
        {preview && (
          <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div><dt className="text-ink-3">Gateways</dt><dd className="text-lg tabular-nums">{preview.sources}</dd></div>
            <div><dt className="text-ink-3">Tasks per hour</dt><dd className="text-lg tabular-nums">{fmt(preview.tasks_per_hour)}</dd></div>
            <div><dt className="text-ink-3">Compute demand</dt><dd className="text-lg tabular-nums">{fmt(preview.demand_mips)} <span className="text-xs text-ink-3">MIPS</span></dd></div>
            <div>
              <dt className="text-ink-3">Share of total capacity</dt>
              <dd className={`text-lg tabular-nums ${load !== null && load !== undefined && load > 0.85 ? "text-danger" : ""}`}>
                {load === null || load === undefined ? "–" : `${fmt(load * 100)}%`}
              </dd>
            </div>
          </dl>
        )}
        <p className="mt-3 text-xs text-ink-3">
          Demand averaged over time. Bursts, network delays and where tasks are placed make real queues longer than this suggests.
        </p>
      </section>

      {save.error && <p className="mt-6 text-sm text-danger">{save.error.message}</p>}
      {save.isSuccess && <p className="mt-6 text-sm text-[var(--st-implemented)]">Saved.</p>}
      <div className="mt-6 flex gap-2 border-t border-line pt-6">
        <Button variant="primary" onClick={doSave} disabled={save.isPending || !spec.name.trim()}>Save workload</Button>
      </div>
    </article>
  );
}
