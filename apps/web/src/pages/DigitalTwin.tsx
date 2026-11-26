import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { type WeatherSource, useTwin } from "@/api/hooks";
import { FarmMap } from "@/components/FarmMap";
import { PageHeader } from "@/components/PageHeader";
import { cn } from "@/lib/cn";
import { KIND_COLORS } from "@/pages/Devices";

const STATUS = [
  { key: "ok", label: "Enough water", color: "#22c55e" },
  { key: "soon", label: "Irrigate soon", color: "#eab308" },
  { key: "now", label: "Irrigate now or stressed", color: "#ef4444" },
  { key: "unknown", label: "No crop data", color: "#94a3b8" },
] as const;

type TwinField = { available_fraction: number | null; action: string | null; stress: boolean | null };

function statusOf(f: TwinField): (typeof STATUS)[number] {
  if (f.available_fraction === null) return STATUS[3];
  if (f.stress || f.action === "irrigate") return STATUS[2];
  if (f.available_fraction < 0.65) return STATUS[1];
  return STATUS[0];
}

const VALUE_FORMAT: Record<string, (v: number) => string> = {
  soil_moisture_m3m3: (v) => `${v.toFixed(3)} m³/m³`,
  air_temperature_c: (v) => `${v.toFixed(1)} °C`,
  relative_humidity_pct: (v) => `${v.toFixed(0)}% RH`,
  rain_mm: (v) => `${v.toFixed(1)} mm rain`,
  valve_open: (v) => (v >= 0.5 ? "valve open" : "valve closed"),
};

export default function DigitalTwin() {
  const [params, setParams] = useSearchParams();
  const source = (params.get("source") as WeatherSource) || "open_meteo";
  const setSource = (v: WeatherSource) => { const p = new URLSearchParams(params); p.set("source", v); setParams(p, { replace: true }); };
  const [useSensors, setUseSensors] = useState(true);
  const [layers, setLayers] = useState({ fields: true, sensors: true, actuators: true, network: true });
  const { data: twin, error, isFetching } = useTwin(source, useSensors);
  const [focus, setFocus] = useState<string | null>(null);

  const farms = twin?.farms ?? [];
  const allFields = farms.flatMap((farm) => farm.fields.map((f) => ({ ...f, farm: farm.name })));
  const allDevices = farms.flatMap((farm) => farm.devices);
  const fit = allFields.flatMap((f) => f.boundary).concat(farms.map((f) => [f.longitude, f.latitude]));
  const show = (kind: string) =>
    kind === "soil_moisture" || kind === "weather_station" ? layers.sensors : kind === "valve" ? layers.actuators : layers.network;
  const focused = allFields.find((f) => f.id === focus);

  const select = "rounded-lg border border-line bg-surface px-3 py-2 text-sm";
  return (
    <>
      <PageHeader
        title="Digital twin & map"
        lead="Every farm on one map: fields coloured by how much water the crop has left, and the devices that measure and irrigate them. It refreshes every minute."
      />
      {twin && farms.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line p-8 text-sm text-ink-2">Nothing to show yet. <Link to="/farms" className="text-accent hover:underline">Create a farm</Link> and draw its fields.</p>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-end gap-4">
            <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">Weather for the water balance</span>
              <select className={select} value={source} onChange={(e) => setSource(e.target.value as WeatherSource)}>
                <option value="open_meteo">Open-Meteo (real weather)</option>
                <option value="csv">My imported station data</option>
                <option value="synthetic">Synthetic (offline)</option>
              </select>
            </label>
            <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={useSensors} onChange={(e) => setUseSensors(e.target.checked)} />Correct with soil-moisture sensors</label>
            <fieldset className="flex flex-wrap gap-3 pb-2 text-sm">
              <legend className="sr-only">Layers</legend>
              {(["fields", "sensors", "actuators", "network"] as const).map((k) => (
                <label key={k} className="flex items-center gap-1.5 capitalize">
                  <input type="checkbox" checked={layers[k]} onChange={(e) => setLayers({ ...layers, [k]: e.target.checked })} />{k}
                </label>
              ))}
            </fieldset>
            {isFetching && <span className="pb-2 text-sm text-ink-3">Updating…</span>}
          </div>
          {error && <p className="mb-4 rounded-xl border border-danger bg-danger-bg p-4 text-sm text-danger">{error.message}</p>}
          <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
            <div>
              <FarmMap
                center={farms[0] ? [farms[0].latitude, farms[0].longitude] : [22.5, 79]}
                zoom={farms[0] ? 15 : 5}
                fields={layers.fields ? allFields.filter((f) => f.boundary.length >= 3).map((f) => {
                  const st = statusOf(f);
                  const pct = f.available_fraction === null ? "" : `, ${Math.round(f.available_fraction * 100)}% water left`;
                  return { id: f.id, name: f.name, boundary: f.boundary, color: st.color, label: `${f.name} (${f.crop})${pct}` };
                }) : []}
                selectedFieldId={focus}
                onFieldClick={setFocus}
                points={allDevices.filter((d) => show(d.kind)).map((d) => {
                  const values = Object.entries(d.latest).map(([m, v]) => VALUE_FORMAT[m]?.(v.value) ?? `${m} ${v.value}`).join(", ");
                  return { id: d.id, name: d.name, lat: d.latitude, lon: d.longitude, color: d.online || d.kind === "gateway" ? KIND_COLORS[d.kind] : "#94a3b8", radius: 6,
                    label: `${d.name}${values ? `: ${values}` : ""}${d.online || d.kind === "gateway" ? "" : " (offline)"}` };
                })}
                fitTo={fit.length ? fit : null}
                className="h-[36rem] overflow-hidden rounded-xl border border-line"
              />
              <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-2">
                {STATUS.map((s) => <li key={s.key} className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-3.5 rounded-sm" style={{ background: s.color }} />{s.label}</li>)}
                {Object.entries(KIND_COLORS).map(([k, c]) => <li key={k} className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: c }} />{k.replace("_", " ")}</li>)}
              </ul>
            </div>
            <aside className="space-y-3">
              {focused && (
                <div className="rounded-xl border border-line bg-surface p-4 text-sm">
                  <p className="text-xs text-ink-3">{focused.farm}</p>
                  <h2 className="font-semibold">{focused.name}</h2>
                  <p className="mt-1 text-ink-2">{focused.advice ?? focused.error ?? "Set a crop and sowing date for this field."}</p>
                  <Link to={`/irrigation?field=${focused.id}&source=${source}`} className="mt-2 inline-block text-accent hover:underline">Open irrigation details</Link>
                </div>
              )}
              <ul className="divide-y divide-line border-y border-line text-sm">
                {allFields.map((f) => {
                  const st = statusOf(f);
                  return (
                    <li key={f.id}>
                      <button type="button" onClick={() => setFocus(f.id)} className={cn("flex w-full items-center gap-3 px-2 py-2.5 text-left hover:bg-surface-2", focus === f.id && "bg-accent-soft")}>
                        <span className="inline-block h-3 w-3 shrink-0 rounded-sm" style={{ background: st.color }} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium">{f.name}</span>
                          <span className="block text-xs text-ink-3">{f.farm}, {f.crop}{f.sensors ? `, ${f.sensors} sensor${f.sensors > 1 ? "s" : ""}` : ""}</span>
                          {f.error && <span className="block text-xs text-danger">{f.error}</span>}
                          {!f.error && !f.sowing_date && <span className="block text-xs text-ink-3">No sowing date set</span>}
                        </span>
                        <span className="text-xs tabular-nums text-ink-2">{f.available_fraction === null ? "–" : `${Math.round(f.available_fraction * 100)}%`}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              {twin && <p className="text-xs text-ink-3">Percentages are the share of the root zone's usable water still available. Updated {new Date(twin.generated_at).toLocaleTimeString()}.</p>}
            </aside>
          </div>
        </>
      )}
    </>
  );
}
