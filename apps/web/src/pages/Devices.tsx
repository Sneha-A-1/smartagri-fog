import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link, useSearchParams } from "react-router-dom";
import type { DeviceT } from "@/api/client";
import {
  useCreateDevice,
  useDeleteDevice,
  useDeviceKinds,
  useDevices,
  useFarms,
  useReadings,
  useResetDeviceToken,
  useUpdateDevice,
} from "@/api/hooks";
import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { FarmMap } from "@/components/FarmMap";
import { PageHeader } from "@/components/PageHeader";
import { OriginBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";

export const KIND_COLORS: Record<string, string> = {
  soil_moisture: "#0ea5e9",
  weather_station: "#f59e0b",
  valve: "#a855f7",
  gateway: "#64748b",
};

const fmtTime = (iso: string) => new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export default function Devices() {
  const [params, setParams] = useSearchParams();
  const { data: farms } = useFarms();
  const farmId = params.get("farm") ?? farms?.[0]?.id ?? "";
  const farm = farms?.find((f) => f.id === farmId);
  const { data: devices, error } = useDevices(farmId || undefined);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [spot, setSpot] = useState<[number, number] | null>(null);
  const current = devices?.find((d) => d.id === selected) ?? null;

  if (farms && farms.length === 0)
    return (
      <>
        <PageHeader title="IoT devices" lead="Sensors, valves and gateways on your farms." />
        <p className="rounded-xl border border-dashed border-line p-8 text-sm text-ink-2">Devices belong to a farm. <Link to="/farms" className="text-accent hover:underline">Create a farm</Link> first.</p>
      </>
    );

  const points = (devices ?? []).map((d) => ({ id: d.id, name: d.name, lat: d.latitude, lon: d.longitude, color: KIND_COLORS[d.kind], radius: 7,
    label: `${d.name} (${d.kind_label.toLowerCase()}${d.online ? "" : ", offline"})` }));
  if (adding && spot) points.push({ id: "new", name: "New device", lat: spot[0], lon: spot[1], color: "#ffffff", radius: 7, label: "New device" });

  return (
    <>
      <PageHeader
        title="IoT devices"
        lead="Soil-moisture sensors, weather stations, valves and gateways. Simulated devices generate readings from the field's water balance; real devices send readings to the platform with a token."
        actions={!adding && farm && <Button variant="primary" onClick={() => { setAdding(true); setSelected(null); setSpot(null); }}>Add device</Button>}
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">Farm</span>
          <select className="rounded-lg border border-line bg-surface px-3 py-2 text-sm" value={farmId}
            onChange={(e) => { const p = new URLSearchParams(params); p.set("farm", e.target.value); setParams(p, { replace: true }); setSelected(null); }}>
            {farms?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        </label>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 pb-2 text-xs text-ink-2">
          {Object.entries(KIND_COLORS).map(([k, c]) => (
            <li key={k} className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: c }} />{k.replace("_", " ")}</li>
          ))}
        </ul>
      </div>
      {error && <p className="mb-4 rounded-xl border border-danger bg-danger-bg p-4 text-sm text-danger">{error.message}</p>}
      {farm && (
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_26rem]">
          <FarmMap
            center={[farm.latitude, farm.longitude]}
            zoom={16}
            fields={farm.fields.filter((f) => f.boundary.length >= 3).map((f) => ({ id: f.id, name: f.name, boundary: f.boundary }))}
            points={points}
            onPointClick={(id) => { if (id !== "new") { setSelected(id); setAdding(false); } }}
            onMapClick={adding ? (lat, lon) => setSpot([lat, lon]) : undefined}
            fitTo={farm.fields.flatMap((f) => f.boundary).length ? farm.fields.flatMap((f) => f.boundary) : [[farm.longitude, farm.latitude]]}
            className="h-[34rem] overflow-hidden rounded-xl border border-line"
          />
          <aside className="space-y-4">
            {adding ? (
              <AddDevice farm={farm} spot={spot} onDone={(id) => { setAdding(false); setSelected(id ?? null); }} />
            ) : (
              <>
                {devices?.length === 0 && (
                  <p className="rounded-xl border border-dashed border-line p-5 text-sm text-ink-2">No devices on this farm yet. Click <strong>Add device</strong>.</p>
                )}
                <ul className="divide-y divide-line border-y border-line text-sm">
                  {devices?.map((d) => (
                    <li key={d.id}>
                      <button type="button" onClick={() => setSelected(d.id)} className={cn("flex w-full items-center gap-3 px-2 py-2.5 text-left hover:bg-surface-2", selected === d.id && "bg-accent-soft")}>
                        <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: KIND_COLORS[d.kind] }} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium">{d.name}</span>
                          <span className="block text-xs text-ink-3">{d.kind_label}{d.simulated ? ", simulated" : ""}</span>
                        </span>
                        <span className={cn("text-xs", d.online ? "text-[var(--st-implemented)]" : "text-ink-3")}>{d.online ? "Online" : d.kind === "gateway" ? "" : "Offline"}</span>
                      </button>
                    </li>
                  ))}
                </ul>
                {current && <DeviceDetail key={current.id} device={current} fieldName={farm.fields.find((f) => f.id === current.field_id)?.name} onDeleted={() => setSelected(null)} />}
              </>
            )}
          </aside>
        </div>
      )}
    </>
  );
}

type FarmLite = { id: string; latitude: number; longitude: number; fields: { id: string; name: string; sowing_date: string | null }[] };

function AddDevice({ farm, spot, onDone }: { farm: FarmLite; spot: [number, number] | null; onDone: (id?: string) => void }) {
  const { data: kinds } = useDeviceKinds();
  const create = useCreateDevice();
  const [f, setF] = useState({ name: "", kind: "soil_moisture", field_id: farm.fields[0]?.id ?? "", simulated: true, interval_min: "30",
    weather_source: "open_meteo", et_pct: "115", noise_sd: "0.01", dropout: "2" });
  const [created, setCreated] = useState<DeviceT | null>(null);
  const needsField = Boolean(kinds?.kinds[f.kind]?.needs_field);
  const input = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm";
  const label = "mb-1 block text-xs text-ink-3";

  if (created?.token) return <TokenInstructions device={created} token={created.token} onClose={() => onDone(created.id)} />;

  return (
    <form className="space-y-3 rounded-xl border border-line bg-surface p-5" onSubmit={(e) => {
      e.preventDefault();
      if (!spot) return;
      create.mutate({ farmId: farm.id, body: {
        name: f.name.trim(), kind: f.kind, field_id: needsField || f.field_id ? f.field_id || null : null,
        latitude: spot[0], longitude: spot[1], simulated: f.simulated, interval_min: Number(f.interval_min) || 30,
        config: { weather_source: f.weather_source, et_multiplier: Number(f.et_pct) / 100, noise_sd: Number(f.noise_sd), dropout: Number(f.dropout) / 100, bias: 0, application_mm_per_h: 5 },
      } }, { onSuccess: (d) => (d.token ? setCreated(d) : onDone(d.id)) });
    }}>
      <h2 className="font-semibold">Add a device</h2>
      <p className={cn("text-sm", spot ? "text-ink-2" : "text-accent")}>{spot ? `Placed at ${spot[0].toFixed(5)}, ${spot[1].toFixed(5)}.` : "Click the device's position on the map."}</p>
      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm"><span className={label}>Type</span>
          <select className={input} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
            {Object.entries(kinds?.kinds ?? {}).map(([k, v]) => <option key={k} value={k}>{String(v.label)}</option>)}
          </select>
        </label>
        <label className="text-sm"><span className={label}>Name</span>
          <input className={input} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
        </label>
      </div>
      {(needsField || f.kind === "weather_station") && (
        <label className="block text-sm"><span className={label}>Field{needsField ? "" : " (optional)"}</span>
          <select className={input} value={f.field_id} onChange={(e) => setF({ ...f, field_id: e.target.value })} required={needsField}>
            {!needsField && <option value="">None</option>}
            {farm.fields.map((x) => <option key={x.id} value={x.id}>{x.name}{x.sowing_date ? "" : " (no sowing date)"}</option>)}
          </select>
        </label>
      )}
      {f.kind !== "gateway" && (
        <>
          <div className="flex gap-4 text-sm">
            <label className="flex items-center gap-2"><input type="radio" checked={f.simulated} onChange={() => setF({ ...f, simulated: true })} />Simulated</label>
            <label className="flex items-center gap-2"><input type="radio" checked={!f.simulated} onChange={() => setF({ ...f, simulated: false })} />Real hardware</label>
          </div>
          <label className="block text-sm"><span className={label}>Reading every (minutes)</span>
            <input className={input} inputMode="numeric" value={f.interval_min} onChange={(e) => setF({ ...f, interval_min: e.target.value })} />
          </label>
        </>
      )}
      {f.simulated && f.kind !== "gateway" && (
        <fieldset className="space-y-3 rounded-lg border border-line p-3">
          <legend className="px-1 text-xs text-ink-3">Simulation</legend>
          <label className="block text-sm"><span className={label}>Weather that drives it</span>
            <select className={input} value={f.weather_source} onChange={(e) => setF({ ...f, weather_source: e.target.value })}>
              <option value="open_meteo">Open-Meteo (real weather)</option>
              <option value="csv">My imported station data</option>
              <option value="synthetic">Synthetic (offline)</option>
            </select>
          </label>
          {f.kind !== "weather_station" && (
            <>
              <label className="block text-sm"><span className={label}>True water use, % of the FAO-56 estimate</span>
                <input className={input} inputMode="numeric" value={f.et_pct} onChange={(e) => setF({ ...f, et_pct: e.target.value })} />
                <span className="mt-1 block text-xs text-ink-3">Real fields rarely match the model. At 115%, the sensor shows the soil drying faster than the model predicts.</span>
              </label>
              {f.kind === "soil_moisture" && (
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-sm"><span className={label}>Noise (m³/m³)</span>
                    <input className={input} inputMode="decimal" value={f.noise_sd} onChange={(e) => setF({ ...f, noise_sd: e.target.value })} />
                  </label>
                  <label className="text-sm"><span className={label}>Missing readings (%)</span>
                    <input className={input} inputMode="numeric" value={f.dropout} onChange={(e) => setF({ ...f, dropout: e.target.value })} />
                  </label>
                </div>
              )}
            </>
          )}
        </fieldset>
      )}
      {create.error && <p className="text-sm text-danger">{create.error.message}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={!spot || !f.name.trim() || create.isPending || (needsField && !f.field_id)}>{create.isPending ? "Adding…" : "Add device"}</Button>
        <Button onClick={() => onDone()}>Cancel</Button>
      </div>
    </form>
  );
}

function TokenInstructions({ device, token, onClose }: { device: DeviceT; token: string; onClose: () => void }) {
  const metric = device.metrics[0] ?? "soil_moisture_m3m3";
  const ps = `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/ingest \`
  -Headers @{ "X-Device-Token" = "${token}" } -ContentType "application/json" \`
  -Body '{"device_id": "${device.id}", "readings": [{"metric": "${metric}", "value": 0.21}]}'`;
  return (
    <div className="space-y-3 rounded-xl border border-accent bg-accent-soft p-5 text-sm">
      <h2 className="font-semibold">Save this device token</h2>
      <p className="text-ink-2">The device sends its readings with this token. It is shown only now; you can create a new one later.</p>
      <code className="block rounded-lg bg-surface p-3 break-all select-all">{token}</code>
      <p className="text-ink-2">To try it, run this in PowerShell while the platform is running:</p>
      <pre className="overflow-x-auto rounded-lg bg-surface p-3 text-xs select-all">{ps}</pre>
      <p className="text-xs text-ink-3">An ESP32 or Raspberry Pi sends the same request (JSON over HTTP). To accept devices on your local network, start the platform with a network address instead of 127.0.0.1 (see docs/devices-and-twin.md).</p>
      <Button variant="primary" onClick={onClose}>Done</Button>
    </div>
  );
}

function DeviceDetail({ device, fieldName, onDeleted }: { device: DeviceT; fieldName?: string; onDeleted: () => void }) {
  const del = useDeleteDevice();
  const reset = useResetDeviceToken();
  const update = useUpdateDevice();
  const [confirm, setConfirm] = useState(false);
  const cfg = device.config as Record<string, number | string>;
  return (
    <div className="space-y-4 rounded-xl border border-line bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{device.name}</h2>
          <p className="text-xs text-ink-3">
            {device.kind_label}{fieldName ? ` in ${fieldName}` : ""}. {device.simulated ? "Simulated" : "Real hardware"}
            {device.kind !== "gateway" && `, every ${device.interval_min} min`}.
            {device.last_seen && ` Last reading ${fmtTime(device.last_seen)}.`}
          </p>
        </div>
        {Object.values(device.latest)[0] && <OriginBadge origin={Object.values(device.latest)[0].origin} />}
      </div>
      {device.note && <p className="rounded-lg bg-danger-bg p-3 text-sm text-danger">{device.note}</p>}
      {device.metrics.map((m) => <MetricChart key={m} deviceId={device.id} metric={m} />)}
      {device.kind === "gateway" && <p className="text-sm text-ink-2">Gateways do not report readings yet. They mark where the farm's network connects; the network simulation will use them.</p>}
      {device.simulated && device.kind !== "gateway" && (
        <p className="text-xs text-ink-3">
          Driven by {cfg.weather_source === "synthetic" ? "synthetic" : cfg.weather_source === "csv" ? "imported station" : "Open-Meteo"} weather
          {device.kind !== "weather_station" && `; true water use ${Math.round(Number(cfg.et_multiplier) * 100)}% of FAO-56`}
          {device.kind === "soil_moisture" && `, noise ${cfg.noise_sd} m³/m³, ${Math.round(Number(cfg.dropout) * 100)}% readings missing`}.
          {device.kind !== "weather_station" && (
            <button type="button" className="ml-1 text-accent hover:underline" disabled={update.isPending}
              onClick={() => update.mutate({ id: device.id, patch: { config: { ...cfg, et_multiplier: Number(cfg.et_multiplier) >= 1.15 ? 1.0 : 1.15 } } })}>
              {Number(cfg.et_multiplier) >= 1.15 ? "Make the field match the model" : "Make the field use 15% more"}
            </button>
          )}
        </p>
      )}
      {reset.data?.token && <TokenInstructions device={device} token={reset.data.token} onClose={() => reset.reset()} />}
      <div className="flex flex-wrap gap-2">
        {!device.simulated && <Button onClick={() => reset.mutate(device.id)} disabled={reset.isPending}>New token</Button>}
        <Button variant="ghost" className="ml-auto" onClick={() => setConfirm(true)}>Delete</Button>
      </div>
      <ConfirmDialog open={confirm} title={`Delete "${device.name}"?`} body="The device and all its readings are removed." confirmLabel="Delete device"
        onCancel={() => setConfirm(false)} onConfirm={() => { del.mutate(device.id); setConfirm(false); onDeleted(); }} />
    </div>
  );
}

function MetricChart({ deviceId, metric }: { deviceId: string; metric: string }) {
  const { data } = useReadings(deviceId, metric, 14);
  if (!data) return null;
  const last = data.points[data.points.length - 1];
  const digits = metric === "soil_moisture_m3m3" ? 3 : 1;
  return (
    <section>
      <div className="flex items-baseline justify-between text-sm">
        <h3 className="font-medium">{data.label}</h3>
        <span className="tabular-nums">{last ? `${last.value.toFixed(digits)} ${data.unit}` : "No readings"}</span>
      </div>
      {data.points.length > 1 && (
        <div className="mt-1 h-32">
          <ResponsiveContainer>
            <LineChart data={data.points.map((p) => ({ ...p, t: new Date(p.ts).getTime() }))} margin={{ top: 4, right: 4, bottom: 0, left: -12 }}>
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} scale="time" tickFormatter={(t) => new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" })} tick={{ fontSize: 11, fill: "var(--ink-3)" }} minTickGap={40} />
              <YAxis tick={{ fontSize: 11, fill: "var(--ink-3)" }} domain={["auto", "auto"]} width={46} tickFormatter={(v) => Number(v).toFixed(digits === 3 ? 2 : 0)} />
              <Tooltip labelFormatter={(t) => fmtTime(new Date(Number(t)).toISOString())} formatter={(v) => [`${Number(v).toFixed(digits)} ${data.unit}`, data.label]} contentStyle={{ fontSize: 12, background: "var(--surface)", border: "1px solid var(--line)" }} />
              <Line dataKey="value" stroke={KIND_COLORS.soil_moisture} strokeWidth={1.5} dot={false} isAnimationActive={false} type={metric === "valve_open" ? "stepAfter" : "monotone"} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="text-[11px] text-ink-3">Last 14 days, {data.total} readings{data.total > data.points.length ? `, averaged into ${data.points.length} points` : ""}.</p>
    </section>
  );
}
