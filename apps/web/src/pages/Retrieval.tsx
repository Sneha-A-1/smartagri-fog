import { useMemo, useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link, useSearchParams } from "react-router-dom";
import type { RetrievalRun } from "@/api/client";
import { useDatasets, useFarms, useRunRetrieval } from "@/api/hooks";
import { Button } from "@/components/Button";
import { PageHeader } from "@/components/PageHeader";
import { OriginBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";

const ARCHS: [string, string][] = [
  ["edge_drf", "Edge: full data retrieval framework"],
  ["edge_sod", "Edge: send-on-delta, no validation"],
  ["cloud_raw", "Cloud: all readings uploaded in batches"],
  ["cloud_periodic", "Cloud: duty-cycled sensors, batched uploads"],
];
const CLASS_COLORS: Record<string, string> = { critical: "#dc2626", high: "#ea580c", medium: "#7c3aed", low: "#64748b" };
const KIND_LABEL: Record<string, string> = { threshold: "Alert", predicted: "Early warning", fault: "Sensor fault" };

type Scenario = { fields: number; days: number; seed: number; soil_noise: number; spike_prob: number; stuck_episodes: number; dropout: number; frost_nights: number; heat_days: number };
type Settings = { validate_range: boolean; validate_spikes: boolean; validate_stuck: boolean; persistence: number; soil_smoothing_min: number; predict: boolean; horizon_min: number; send_on_delta: boolean; soil_deadband: number; temperature_deadband: number; heartbeat_min: number };

const DEFAULT_SCENARIO: Scenario = { fields: 6, days: 14, seed: 1, soil_noise: 0.01, spike_prob: 0.005, stuck_episodes: 0.3, dropout: 0.02, frost_nights: 2, heat_days: 1 };
const DEFAULT_SETTINGS: Settings = { validate_range: true, validate_spikes: true, validate_stuck: true, persistence: 2, soil_smoothing_min: 60, predict: true, horizon_min: 360, send_on_delta: true, soil_deadband: 0.01, temperature_deadband: 0.5, heartbeat_min: 120 };

export default function Retrieval() {
  const { data: farms } = useFarms();
  const { data: datasets } = useDatasets();
  const [params] = useSearchParams();
  const run = useRunRetrieval();
  const [source, setSource] = useState<"scenario" | "devices" | "dataset">(params.get("dataset") ? "dataset" : "scenario");
  const [datasetId, setDatasetId] = useState(params.get("dataset") ?? "");
  const dataset = datasetId || datasets?.[0]?.id || "";
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO);
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [architecture, setArchitecture] = useState("edge_drf");
  const [farmId, setFarmId] = useState("");
  const [days, setDays] = useState(7);
  const farm = farmId || farms?.[0]?.id || "";

  const go = () => run.mutate({ source, scenario, settings, architecture, farm_id: farm || null, days, dataset_id: dataset || null });

  const num = (label: string, value: number, onChange: (v: number) => void, step = "any", hint?: string) => (
    <label className="block text-sm">
      <span className="mb-1 block text-xs text-ink-3">{label}</span>
      <input type="number" step={step} className="w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm" value={value}
        onChange={(e) => onChange(Number(e.target.value))} />
      {hint && <span className="mt-0.5 block text-[11px] text-ink-3">{hint}</span>}
    </label>
  );
  const check = (label: string, k: keyof Settings) => (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={Boolean(settings[k])} onChange={(e) => setSettings({ ...settings, [k]: e.target.checked })} />{label}
    </label>
  );

  return (
    <>
      <PageHeader
        title="Data retrieval framework"
        lead="What the edge node does with raw sensor streams: validate readings, detect and predict events, send only what matters upstream, and turn alerts into urgent tasks for the scheduler."
      />
      <div className="grid gap-8 xl:grid-cols-[19rem_minmax(0,1fr)]">
        <aside className="space-y-5 xl:sticky xl:top-4 xl:self-start">
          <fieldset className="space-y-3 rounded-xl border border-line bg-surface p-4">
            <legend className="px-1 text-sm font-medium">Input</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
              <label className="flex items-center gap-2"><input type="radio" checked={source === "scenario"} onChange={() => setSource("scenario")} />Synthetic scenario</label>
              <label className="flex items-center gap-2"><input type="radio" checked={source === "devices"} onChange={() => setSource("devices")} />My devices</label>
              <label className="flex items-center gap-2"><input type="radio" checked={source === "dataset"} onChange={() => setSource("dataset")} />Dataset</label>
            </div>
            {source === "dataset" ? (
              datasets?.length === 0 ? (
                <p className="text-sm text-ink-2">No datasets yet. <Link to="/data/acquisition" className="text-accent hover:underline">Upload one</Link>.</p>
              ) : (
                <>
                  <label className="block text-sm"><span className="mb-1 block text-xs text-ink-3">Dataset</span>
                    <select className="w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm" value={dataset} onChange={(e) => setDatasetId(e.target.value)}>
                      {datasets?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                    </select>
                  </label>
                  <p className="text-xs text-ink-3">Uses the column mapping saved on the <Link to={`/data/acquisition?dataset=${dataset}`} className="text-accent hover:underline">Data acquisition</Link> page.</p>
                </>
              )
            ) : source === "scenario" ? (
              <>
                <p className="text-xs text-ink-3">Soil probes and a weather station with known events and injected sensor faults, so every alert can be checked.</p>
                <div className="grid grid-cols-2 gap-3">
                  {num("Fields", scenario.fields, (v) => setScenario({ ...scenario, fields: v }), "1")}
                  {num("Days", scenario.days, (v) => setScenario({ ...scenario, days: v }), "1")}
                  {num("Soil noise (m³/m³)", scenario.soil_noise, (v) => setScenario({ ...scenario, soil_noise: v }))}
                  {num("Spikes (share)", scenario.spike_prob, (v) => setScenario({ ...scenario, spike_prob: v }))}
                  {num("Stuck episodes", scenario.stuck_episodes, (v) => setScenario({ ...scenario, stuck_episodes: v }))}
                  {num("Missing (share)", scenario.dropout, (v) => setScenario({ ...scenario, dropout: v }))}
                  {num("Frost nights", scenario.frost_nights, (v) => setScenario({ ...scenario, frost_nights: v }), "1")}
                  {num("Seed", scenario.seed, (v) => setScenario({ ...scenario, seed: v }), "1")}
                </div>
                <label className="block text-sm">
                  <span className="mb-1 block text-xs text-ink-3">Architecture</span>
                  <select className="w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm" value={architecture} onChange={(e) => setArchitecture(e.target.value)}>
                    {ARCHS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </label>
              </>
            ) : (
              <>
                {farms?.length === 0 ? (
                  <p className="text-sm text-ink-2">No farms yet. <Link to="/farms" className="text-accent hover:underline">Create one</Link> and add devices.</p>
                ) : (
                  <label className="block text-sm"><span className="mb-1 block text-xs text-ink-3">Farm</span>
                    <select className="w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm" value={farm} onChange={(e) => setFarmId(e.target.value)}>
                      {farms?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                    </select>
                  </label>
                )}
                {num("Past days", days, setDays, "1")}
                <p className="text-xs text-ink-3">Uses the soil-moisture sensors and weather stations on the IoT devices page.</p>
              </>
            )}
          </fieldset>
          <fieldset className="space-y-3 rounded-xl border border-line bg-surface p-4">
            <legend className="px-1 text-sm font-medium">Framework</legend>
            <div className="space-y-1.5">
              <p className="text-xs text-ink-3">Validate</p>
              {check("Physical range", "validate_range")}
              {check("Spikes (Hampel filter)", "validate_spikes")}
              {check("Stuck sensors", "validate_stuck")}
            </div>
            <div className="grid grid-cols-2 gap-3">
              {num("Persistence (readings)", settings.persistence, (v) => setSettings({ ...settings, persistence: v }), "1")}
              {num("Soil smoothing (min)", settings.soil_smoothing_min, (v) => setSettings({ ...settings, soil_smoothing_min: v }), "1")}
            </div>
            {check("Early warnings from trends", "predict")}
            {settings.predict && num("Warning horizon (min)", settings.horizon_min, (v) => setSettings({ ...settings, horizon_min: v }), "1")}
            {check("Send on delta", "send_on_delta")}
            {settings.send_on_delta && (
              <div className="grid grid-cols-2 gap-3">
                {num("Soil dead band", settings.soil_deadband, (v) => setSettings({ ...settings, soil_deadband: v }))}
                {num("Temp. dead band (°C)", settings.temperature_deadband, (v) => setSettings({ ...settings, temperature_deadband: v }))}
                {num("Heartbeat (min)", settings.heartbeat_min, (v) => setSettings({ ...settings, heartbeat_min: v }), "1")}
              </div>
            )}
            <button type="button" className="text-xs text-accent hover:underline" onClick={() => setSettings(DEFAULT_SETTINGS)}>Reset to defaults</button>
          </fieldset>
          <Button variant="primary" className="w-full" disabled={run.isPending || (source === "devices" && !farm) || (source === "dataset" && !dataset)} onClick={go}>
            {run.isPending ? "Running…" : "Run the framework"}
          </Button>
          <p className="text-xs text-ink-3">
            For statistics over many scenarios, run{" "}
            <Link to="/algorithms/simulation:retrieval_evaluation" className="text-accent hover:underline">Experiment: data retrieval architectures</Link>.
          </p>
        </aside>
        <section className="min-w-0">
          {run.error && <p className="rounded-xl border border-danger bg-danger-bg p-4 text-sm text-danger">{run.error.message}</p>}
          {!run.data && !run.error && (
            <div className="rounded-xl border border-dashed border-line p-8 text-sm text-ink-2">
              <p className="font-medium text-ink">Choose an input and click Run.</p>
              <p className="mt-1">You'll see every reading with its validation result, what was sent upstream, the alerts and early warnings, and the tasks handed to the scheduler.</p>
            </div>
          )}
          {run.data && <RunView run={run.data} />}
        </section>
      </div>
    </>
  );
}

function RunView({ run }: { run: RetrievalRun }) {
  const [streamKey, setStreamKey] = useState(run.streams[0]?.key ?? "");
  const stream = run.streams.find((s) => s.key === streamKey) ?? run.streams[0];
  const start = new Date(run.start).getTime();
  const when = (t: number) => new Date(start + t * 60_000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const s = run.summary as Record<string, number & Record<string, number>>;
  const ev = run.evaluation;
  const alerts = run.events.filter((e) => e.kind === "threshold");
  const streamEvents = run.events.filter((e) => e.stream === stream?.key);
  const trueEvents = ((run.true_events ?? []) as TrueEvent[]).filter((e) => e.stream === stream?.key);

  const data = useMemo(() => {
    if (!stream) return { ok: [], flagged: [], sent: [], truth: [] };
    const ok: { t: number; v: number }[] = [];
    const flagged: { t: number; v: number; status: string }[] = [];
    stream.raw.forEach(([t, v], i) => {
      if (v === null || t === null) return;
      if (stream.status[i] === "ok") ok.push({ t, v });
      else if (stream.status[i] !== "missing") flagged.push({ t, v, status: stream.status[i] });
    });
    return { ok, flagged, sent: stream.transmitted.map(([t, v]) => ({ t, v })), truth: (stream.truth ?? []).map(([t, v]) => ({ t, v })) };
  }, [stream]);

  const download = (name: string, payload: unknown) => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 1)], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    a.click();
    URL.revokeObjectURL(url);
  };
  const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="text-sm text-ink-2">{run.architecture_label}. {run.streams.length} streams over {Math.round(run.horizon_min / 1440)} days.</p>
        <OriginBadge origin={run.data_origin} />
      </div>
      {run.notes.length > 0 && <ul className="rounded-lg bg-surface-2 p-3 text-sm text-ink-2">{run.notes.map((n) => <li key={n}>{n}</li>)}</ul>}

      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
        <div><dt className="text-ink-3">Readings</dt><dd className="text-lg tabular-nums">{s.samples.toLocaleString()}</dd></div>
        <div><dt className="text-ink-3">Sent upstream</dt><dd className="text-lg tabular-nums">{pct(1 - s.reduction)}</dd></div>
        <div><dt className="text-ink-3">Alerts</dt><dd className="text-lg tabular-nums">{alerts.length}</dd></div>
        <div><dt className="text-ink-3">Early warnings</dt><dd className="text-lg tabular-nums">{run.events.filter((e) => e.kind === "predicted").length}</dd></div>
        <div><dt className="text-ink-3">Sensor faults</dt><dd className="text-lg tabular-nums">{run.events.filter((e) => e.kind === "fault").length}</dd></div>
        <div><dt className="text-ink-3">Urgent tasks</dt><dd className="text-lg tabular-nums">{s.urgent_tasks}</dd></div>
      </dl>

      {ev && (
        <section className="rounded-xl border border-line bg-surface p-4">
          <h3 className="text-sm font-medium">Checked against the scenario's ground truth</h3>
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
            <div><dt className="text-ink-3">Alert precision</dt><dd className="tabular-nums">{pct(ev.precision)}</dd></div>
            <div><dt className="text-ink-3">Events alerted (recall)</dt><dd className="tabular-nums">{pct(ev.recall)}</dd></div>
            <div><dt className="text-ink-3">False alarms per day</dt><dd className="tabular-nums">{ev.false_alarms_per_day?.toFixed(1) ?? "–"}</dd></div>
            <div><dt className="text-ink-3">Frost and heat detected after</dt><dd className="tabular-nums">{ev.time_to_detect_min === null ? "–" : `${ev.time_to_detect_min.toFixed(0)} min`}</dd></div>
            <div><dt className="text-ink-3">Events with early warning</dt><dd className="tabular-nums">{pct(ev.early_warning_share)}</dd></div>
            <div><dt className="text-ink-3">Stuck sensors detected</dt><dd className="tabular-nums">{pct(ev.fault_recall)}</dd></div>
            <div><dt className="text-ink-3">Age of data at the scheduler</dt><dd className="tabular-nums">{ev.urgent_aoi_min === null ? "–" : `${ev.urgent_aoi_min.toFixed(1)} min`}</dd></div>
            <div><dt className="text-ink-3">Soil reconstruction error</dt><dd className="tabular-nums">{ev.soil_rmse?.toFixed(3) ?? "–"} m³/m³</dd></div>
          </dl>
        </section>
      )}

      {stream && (
        <section>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">Stream</span>
              <select className="rounded-lg border border-line bg-surface px-3 py-2 text-sm" value={stream.key} onChange={(e) => setStreamKey(e.target.value)}>
                {run.streams.map((x) => <option key={x.key} value={x.key}>{x.source}, {x.label.toLowerCase()} ({x.group})</option>)}
              </select>
            </label>
            <p className="text-xs text-ink-3">
              {stream.raw.length} readings, {stream.transmitted.length} sent, {stream.status.filter((x) => x !== "ok" && x !== "missing").length} rejected.
            </p>
          </div>
          <div className="mt-3 h-80">
            <ResponsiveContainer>
              <ComposedChart margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="var(--line)" vertical={false} />
                <XAxis dataKey="t" type="number" domain={[0, run.horizon_min]} tickFormatter={(t) => when(Number(t)).split(",")[0]} minTickGap={50} tick={{ fontSize: 12, fill: "var(--ink-3)" }} allowDuplicatedCategory={false} />
                <YAxis dataKey="v" type="number" domain={["auto", "auto"]} tick={{ fontSize: 12, fill: "var(--ink-3)" }} tickFormatter={(v) => Number(v).toFixed(stream.metric.startsWith("soil") ? 2 : 0)} width={48}
                  label={{ value: stream.unit, angle: -90, position: "insideLeft", fontSize: 12, fill: "var(--ink-3)" }} />
                <Tooltip labelFormatter={(t) => when(Number(t))} formatter={(v) => Number(v).toFixed(3)} contentStyle={{ fontSize: 12, background: "var(--surface)", border: "1px solid var(--line)" }} />
                <Legend wrapperStyle={{ fontSize: 13 }} />
                {trueEvents.filter((e) => e.name !== "stuck").map((e) => (
                  <ReferenceArea key={`${e.name}-${e.onset}`} x1={e.onset} x2={e.end} fill="#ef4444" fillOpacity={0.08} />
                ))}
                {trueEvents.filter((e) => e.name === "stuck").map((e) => (
                  <ReferenceArea key={`stuck-${e.onset}`} x1={e.onset} x2={e.end} fill="#7c3aed" fillOpacity={0.08} />
                ))}
                {stream.threshold !== null && <ReferenceLine y={stream.threshold} stroke="var(--danger)" strokeDasharray="5 4" />}
                {streamEvents.slice(0, 60).map((e, i) => (
                  <ReferenceLine key={`${e.kind}-${e.t}-${i}`} x={e.t} stroke={e.kind === "predicted" ? "#eab308" : e.kind === "fault" ? "#7c3aed" : CLASS_COLORS[e.task_class]} strokeWidth={1.5} />
                ))}
                <Scatter data={data.ok} name="Valid reading" fill="var(--ink-3)" fillOpacity={0.35} shape={<Dot r={1.6} />} isAnimationActive={false} />
                <Scatter data={data.flagged} name="Rejected" fill="#dc2626" shape={<Dot r={2.8} />} isAnimationActive={false} />
                {data.truth.length > 0 && <Line data={data.truth} dataKey="v" name="Truth" stroke="var(--ink)" strokeDasharray="4 3" strokeWidth={1} dot={false} isAnimationActive={false} />}
                <Line data={data.sent} dataKey="v" name="Sent upstream" type="stepAfter" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-1 text-xs text-ink-3">
            Vertical lines: alerts (orange/red), early warnings (yellow) and sensor faults (purple). Dashed line: the threshold.
            {run.true_events && " Shaded: the true events (red) and stuck-sensor episodes (purple)."}
          </p>
        </section>
      )}

      <section>
        <h3 className="font-semibold">Events on this stream</h3>
        {streamEvents.length === 0 ? <p className="mt-2 text-sm text-ink-3">None.</p> : (
          <ul className="mt-2 divide-y divide-line border-y border-line text-sm">
            {streamEvents.slice(0, 50).map((e, i) => (
              <li key={`${e.t}-${i}`} className="flex flex-wrap gap-x-4 py-2">
                <span className="w-36 text-ink-3">{when(e.t)}</span>
                <span className="w-28 font-medium">{KIND_LABEL[e.kind]}</span>
                <span className="flex-1">{e.name.replace("_", " ")}{e.value !== null && `, ${e.value.toFixed(3)} ${stream?.unit ?? ""}`}{e.eta_min !== null && `, crossing expected in ${Math.round(e.eta_min / 60)} h`}</span>
                {e.kind !== "predicted" && <span className="text-xs" style={{ color: CLASS_COLORS[e.task_class] }}>{e.task_class}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="font-semibold">Tasks for the scheduler</h3>
          <div className="flex gap-2">
            <Button onClick={() => download("retrieval-tasks.json", run.tasks)}>Download tasks (JSON)</Button>
            <Button variant="ghost" onClick={() => download("retrieval-run.json", run)}>Download full run</Button>
          </div>
        </div>
        <p className="mt-1 text-sm text-ink-2">
          Urgent tasks (critical, high) come from alerts and go to AURA's online tier; maintenance (medium) from sensor faults;
          aggregation (low) every hour from the data sent upstream. Age of data = arrival minus the newest reading the task uses.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead className="text-left text-ink-3">
              <tr className="border-b border-line">
                <th className="py-2 pr-3 font-normal">Arrives</th><th className="py-2 pr-3 font-normal">Class</th><th className="py-2 pr-3 font-normal">Type</th>
                <th className="py-2 pr-3 font-normal">From</th><th className="py-2 pr-3 text-right font-normal">Age of data</th><th className="py-2 text-right font-normal">Deadline in</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {run.tasks.filter((t) => t.task_class !== "low").slice(0, 100).map((t) => (
                <tr key={t.id}>
                  <td className="py-1.5 pr-3 whitespace-nowrap">{when(t.arrival)}</td>
                  <td className={cn("py-1.5 pr-3 font-medium")} style={{ color: CLASS_COLORS[t.task_class] }}>{t.task_class}</td>
                  <td className="py-1.5 pr-3">{t.task_type.replace("_", " ")}</td>
                  <td className="py-1.5 pr-3 text-ink-2">{t.stream.split(":")[0]}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{(t.arrival - t.data_time).toFixed(1)} min</td>
                  <td className="py-1.5 text-right tabular-nums">{(t.deadline - t.arrival).toFixed(0)} min</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-xs text-ink-3">{run.tasks.filter((t) => t.task_class === "low").length} aggregation tasks not listed.</p>
        </div>
      </section>
    </div>
  );
}

type TrueEvent = { stream: string; name: string; onset: number; end: number };

function Dot({ cx, cy, r, fill, fillOpacity }: { cx?: number; cy?: number; r: number; fill?: string; fillOpacity?: number }) {
  if (cx === undefined || cy === undefined) return null;
  return <circle cx={cx} cy={cy} r={r} fill={fill} fillOpacity={fillOpacity} />;
}
