import { useRef, useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link, useSearchParams } from "react-router-dom";
import { type WeatherSource, useAgroPresets, useFarmWeather, useFarms, useImportWeatherCsv } from "@/api/hooks";
import { Button } from "@/components/Button";
import { PageHeader } from "@/components/PageHeader";
import { OriginBadge } from "@/components/StatusBadge";

const iso = (d: Date) => d.toISOString().slice(0, 10);
const shortDate = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

export default function Weather() {
  const [params, setParams] = useSearchParams();
  const { data: farms } = useFarms();
  const farmId = params.get("farm") ?? farms?.[0]?.id ?? "";
  const source = (params.get("source") as WeatherSource) || "open_meteo";
  const today = new Date();
  const [range, setRange] = useState({ start: iso(new Date(today.getTime() - 60 * 864e5)), end: iso(new Date(today.getTime() + 7 * 864e5)) });
  const { data: w, error, isFetching } = useFarmWeather(farmId, source, range.start, range.end);
  const set = (k: string, v: string) => { const p = new URLSearchParams(params); p.set(k, v); setParams(p, { replace: true }); };

  const input = "rounded-lg border border-line bg-surface px-3 py-2 text-sm";
  const data = (w?.days ?? []).map((d) => ({ ...d, day: String(d.day), et0: Math.round(d.et0 * 100) / 100, rain: d.rain || null }));
  const total = (k: "rain" | "et0") => (w?.days ?? []).filter((d) => !d.forecast).reduce((s, d) => s + (d[k] ?? 0), 0);

  return (
    <>
      <PageHeader title="Weather & climate" lead="Daily weather for each farm, and the reference evapotranspiration (ET₀) computed from it with the FAO-56 Penman-Monteith equation." />
      {farms?.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line p-8 text-sm text-ink-2">Weather is shown per farm. <Link to="/farms" className="text-accent hover:underline">Create a farm</Link> first.</p>
      ) : (
        <>
          <div className="mb-6 flex flex-wrap items-end gap-3">
            <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">Farm</span>
              <select className={input} value={farmId} onChange={(e) => set("farm", e.target.value)}>
                {farms?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </label>
            <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">Source</span>
              <select className={input} value={source} onChange={(e) => set("source", e.target.value)}>
                <option value="open_meteo">Open-Meteo (real weather)</option>
                <option value="csv">My imported station data</option>
                <option value="synthetic">Synthetic (offline demo)</option>
              </select>
            </label>
            <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">From</span>
              <input type="date" className={input} value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} />
            </label>
            <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">To</span>
              <input type="date" className={input} value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} />
            </label>
            {isFetching && <span className="pb-2 text-sm text-ink-3">Loading weather…</span>}
          </div>
          {source === "csv" && farmId && <CsvImport farmId={farmId} />}
          {error && <p className="rounded-xl border border-danger bg-danger-bg p-4 text-sm text-danger">{error.message}</p>}
          {w && w.days.length === 0 && <p className="text-sm text-ink-2">No weather for these dates{source === "csv" ? "; import a CSV file above" : ""}.</p>}
          {w && w.days.length > 0 && (
            <div className="space-y-8">
              <div className="flex flex-wrap items-baseline justify-between gap-3 text-sm text-ink-2">
                <p>{w.source_description}. Rain {Math.round(total("rain"))} mm and ET₀ {Math.round(total("et0"))} mm over the observed days.</p>
                <OriginBadge origin={w.data_origin} />
              </div>
              <Chart title="Temperature" unit="°C" data={data} lines={[["tmax", "Maximum", "var(--danger)"], ["tmin", "Minimum", "var(--st-integration)"]]} />
              <Chart title="Rain and reference evapotranspiration" unit="mm/day" data={data} bars={[["rain", "Rain", "var(--st-integration)"]]}
                lines={[["et0", "ET₀ (FAO-56, this platform)", "var(--accent)"], ...(source === "open_meteo" ? [["et0_reference", "ET₀ reported by Open-Meteo", "var(--ink-3)"] as [string, string, string]] : [])]} />
              {w.et0_mean_abs_difference !== null && (
                <p className="max-w-3xl text-xs text-ink-3">
                  This platform's ET₀ differs from Open-Meteo's by {w.et0_mean_abs_difference.toFixed(2)} mm/day on average.
                  Both use FAO-56 Penman-Monteith; differences come from daily versus hourly calculation and how humidity and wind are aggregated.
                </p>
              )}
              {w.days.some((d) => d.radiation_estimated) && (
                <p className="max-w-3xl text-xs text-ink-3">Solar radiation was missing on some days and was estimated from the temperature range (FAO-56 eq. 50), which makes ET₀ less precise.</p>
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}

function Chart({ title, unit, data, lines, bars = [] }: { title: string; unit: string; data: Record<string, unknown>[]; lines: [string, string, string][]; bars?: [string, string, string][] }) {
  return (
    <section>
      <h3 className="text-sm font-medium">{title} <span className="font-normal text-ink-3">({unit})</span></h3>
      <div className="mt-2 h-64">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis dataKey="day" tickFormatter={shortDate} minTickGap={28} tick={{ fontSize: 12, fill: "var(--ink-3)" }} />
            <YAxis tick={{ fontSize: 12, fill: "var(--ink-3)" }} />
            <Tooltip labelFormatter={(d) => shortDate(String(d))} contentStyle={{ fontSize: 13, background: "var(--surface)", border: "1px solid var(--line)" }} />
            <Legend wrapperStyle={{ fontSize: 13 }} />
            {bars.map(([k, n, c]) => <Bar key={k} dataKey={k} name={n} fill={c} fillOpacity={0.5} isAnimationActive={false} />)}
            {lines.map(([k, n, c]) => <Line key={k} dataKey={k} name={n} stroke={c} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />)}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function CsvImport({ farmId }: { farmId: string }) {
  const ref = useRef<HTMLInputElement>(null);
  const imp = useImportWeatherCsv();
  const { data: presets } = useAgroPresets();
  return (
    <div className="mb-6 rounded-xl border border-line bg-surface p-4 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <input ref={ref} type="file" accept=".csv,text/csv" className="hidden" aria-label="Weather CSV file"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) imp.mutate({ farmId, file: f }); e.target.value = ""; }} />
        <Button variant="primary" disabled={imp.isPending} onClick={() => ref.current?.click()}>{imp.isPending ? "Importing…" : "Import station CSV"}</Button>
        {imp.data && <span role="status">Imported {imp.data.imported} days.{imp.data.errors.length > 0 && ` ${imp.data.errors.length} rows skipped.`}</span>}
        {imp.error && <span className="text-danger">{imp.error.message}</span>}
      </div>
      {imp.data && imp.data.errors.length > 0 && <p className="mt-2 text-xs text-ink-3">{imp.data.errors.slice(0, 3).join(" ")}</p>}
      <details className="mt-3">
        <summary className="cursor-pointer text-ink-2">CSV format</summary>
        <p className="mt-2 text-ink-2">One row per day with a header row. Columns (date, tmax and tmin are required):</p>
        <ul className="mt-1 grid gap-x-6 sm:grid-cols-2">
          {Object.entries(presets?.csv_columns ?? {}).map(([k, v]) => <li key={k}><code>{k}</code>: <span className="text-ink-3">{v}</span></li>)}
        </ul>
      </details>
    </div>
  );
}
