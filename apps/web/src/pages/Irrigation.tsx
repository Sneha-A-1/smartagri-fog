import { Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link, useSearchParams } from "react-router-dom";
import { type WeatherSource, useFarms, useWaterBalance } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { OriginBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";

const SOURCES: [WeatherSource, string][] = [
  ["open_meteo", "Open-Meteo (real weather)"],
  ["csv", "My imported station data"],
  ["synthetic", "Synthetic (offline demo)"],
];

const shortDate = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

export default function Irrigation() {
  const [params, setParams] = useSearchParams();
  const { data: farms } = useFarms();
  const allFields = (farms ?? []).flatMap((farm) => farm.fields.map((f) => ({ ...f, farmName: farm.name })));
  const fieldId = params.get("field") ?? allFields.find((f) => f.sowing_date)?.id ?? "";
  const source = (params.get("source") as WeatherSource) || "open_meteo";
  const useSensors = params.get("sensors") === "1";
  const { data: wb, error, isFetching } = useWaterBalance(fieldId, source, useSensors);
  const set = (k: string, v: string) => { const p = new URLSearchParams(params); p.set(k, v); setParams(p, { replace: true }); };

  const select = "rounded-lg border border-line bg-surface px-3 py-2 text-sm";
  return (
    <>
      <PageHeader
        title="Smart irrigation"
        lead="How much water each field's crop is using, how much is left in the root zone, and when to irrigate, from the FAO-56 method and daily weather."
      />
      {farms && allFields.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line p-8 text-sm text-ink-2">
          Add a farm and draw a field first, then set its crop and sowing date. <Link to="/farms" className="text-accent hover:underline">Go to Farms</Link>
        </p>
      ) : (
        <>
          <div className="mb-6 flex flex-wrap items-end gap-3">
            <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">Field</span>
              <select className={select} value={fieldId} onChange={(e) => set("field", e.target.value)}>
                {(farms ?? []).map((farm) => (
                  <optgroup key={farm.id} label={farm.name}>
                    {farm.fields.map((f) => <option key={f.id} value={f.id} disabled={!f.sowing_date}>{f.name}{f.sowing_date ? "" : " (no sowing date)"}</option>)}
                  </optgroup>
                ))}
              </select>
            </label>
            <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">Weather</span>
              <select className={select} value={source} onChange={(e) => set("source", e.target.value)}>
                {SOURCES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2 pb-2 text-sm">
              <input type="checkbox" checked={useSensors} onChange={(e) => set("sensors", e.target.checked ? "1" : "0")} />
              Correct with soil-moisture sensors
            </label>
            {isFetching && <span className="pb-2 text-sm text-ink-3">Calculating…</span>}
          </div>
          {error && (
            <p className="rounded-xl border border-danger bg-danger-bg p-4 text-sm text-danger">
              {error.message}
              {source === "open_meteo" && " You can switch the weather to Synthetic to try the page offline."}
            </p>
          )}
          {wb && <BalanceView wb={wb} />}
        </>
      )}
    </>
  );
}

function BalanceView({ wb }: { wb: NonNullable<ReturnType<typeof useWaterBalance>["data"]> }) {
  const rec = wb.recommendation as { action: string; text: string; depletion_mm?: number; trigger_mm?: number; days_until?: number | null; gross_mm?: number };
  const last = [...wb.days].reverse().find((d) => !d.forecast) ?? wb.days[wb.days.length - 1];
  const data = wb.days.map((d) => ({
    day: d.day,
    available: Math.round((d.taw - d.depletion) * 10) / 10,
    threshold: Math.round((d.taw - d.raw) * 10) / 10,
    taw: Math.round(d.taw),
    rain: d.rain || null,
    irrigation: d.irrigation_gross || null,
    et0: Math.round(d.et0 * 100) / 100,
    etc: Math.round(d.etc_adj * 100) / 100,
    kc: Math.round(d.kc * 100) / 100,
    model: d.model_depletion === null || d.model_depletion === undefined ? null : Math.round((d.taw - d.model_depletion) * 10) / 10,
  }));
  const corrected = wb.sensors_used > 0;
  const firstForecast = wb.days.find((d) => d.forecast)?.day;
  const s = wb.summary;
  const tone = rec.action === "irrigate" ? "border-accent bg-accent-soft" : "border-line bg-surface";
  const mm = (v: unknown) => (typeof v === "number" ? `${Math.round(v)} mm` : "–");

  return (
    <div className="space-y-8">
      <section className={cn("rounded-xl border p-5", tone)}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs text-ink-3">{wb.field_name}, {wb.crop.name.toLowerCase()}, day {last ? last.stage_day + 1 : 0} of {wb.crop.stages.reduce((a, b) => a + b, 0)}</p>
            <h2 className="mt-1 text-xl font-semibold">{rec.action === "irrigate" ? "Irrigate now" : rec.action === "rainfed" ? "Rainfed field" : "No irrigation needed today"}</h2>
            <p className="mt-1 max-w-2xl text-sm text-ink-2">{rec.text}</p>
          </div>
          <OriginBadge origin={wb.data_origin} />
        </div>
        {last && (
          <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div><dt className="text-ink-3">Water left for the crop</dt><dd className="text-lg tabular-nums">{Math.round(last.taw - last.depletion)} of {Math.round(last.taw)} mm</dd></div>
            <div><dt className="text-ink-3">Stress starts below</dt><dd className="text-lg tabular-nums">{Math.round(last.taw - last.raw)} mm</dd></div>
            <div><dt className="text-ink-3">Crop water use today</dt><dd className="text-lg tabular-nums">{last.etc_adj.toFixed(1)} mm</dd></div>
            <div><dt className="text-ink-3">Water stress</dt><dd className="text-lg">{last.ks < 1 ? `Yes (Ks ${last.ks.toFixed(2)})` : "None"}</dd></div>
          </dl>
        )}
      </section>

      <section>
        <h3 className="font-semibold">Water in the root zone</h3>
        <p className="mt-1 text-sm text-ink-2">
          The line falls as the crop uses water and rises with rain and irrigation. Below the dashed line the crop is
          stressed.{firstForecast && " The shaded days are forecast."}
          {corrected && ` Each evening the model is reset to what the field's ${wb.sensors_used > 1 ? `${wb.sensors_used} sensors` : "sensor"} measured; the dotted line shows what the model alone expected that day. Summed over the season, the corrections add up to ${Math.abs(Math.round(Number(s.sensor_correction_mm)))} mm: the field ${Number(s.sensor_correction_mm) >= 0 ? "used more" : "used less"} water than the model expected (day-to-day differences also include sensor noise).`}
        </p>
        <div className="mt-3 h-80">
          <ResponsiveContainer>
            <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis dataKey="day" tickFormatter={shortDate} minTickGap={28} tick={{ fontSize: 12, fill: "var(--ink-3)" }} />
              <YAxis yAxisId="w" tick={{ fontSize: 12, fill: "var(--ink-3)" }} label={{ value: "mm available", angle: -90, position: "insideLeft", fontSize: 12, fill: "var(--ink-3)" }} />
              <YAxis yAxisId="p" orientation="right" tick={{ fontSize: 12, fill: "var(--ink-3)" }} label={{ value: "mm rain, irrigation", angle: 90, position: "insideRight", fontSize: 12, fill: "var(--ink-3)" }} />
              <Tooltip labelFormatter={(d) => shortDate(String(d))} contentStyle={{ fontSize: 13, background: "var(--surface)", border: "1px solid var(--line)" }} />
              <Legend wrapperStyle={{ fontSize: 13 }} />
              {firstForecast && <ReferenceArea yAxisId="w" x1={firstForecast} x2={data[data.length - 1].day} fill="var(--surface-2)" fillOpacity={0.8} />}
              <Bar yAxisId="p" dataKey="rain" name="Rain" fill="var(--st-integration)" fillOpacity={0.5} isAnimationActive={false} />
              <Bar yAxisId="p" dataKey="irrigation" name="Irrigation (applied)" fill="var(--accent)" isAnimationActive={false} />
              <Line yAxisId="w" dataKey="taw" name="Full (field capacity)" stroke="var(--ink-3)" strokeWidth={1} dot={false} isAnimationActive={false} />
              <Line yAxisId="w" dataKey="threshold" name="Stress threshold" stroke="var(--danger)" strokeDasharray="5 4" strokeWidth={1.5} dot={false} isAnimationActive={false} />
              {corrected && <Line yAxisId="w" dataKey="model" name="Model before sensor correction" stroke="var(--ink-3)" strokeDasharray="2 3" strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />}
              <Line yAxisId="w" dataKey="available" name={corrected ? "Water available (sensor-corrected)" : "Water available"} stroke="var(--st-implemented)" strokeWidth={2.5} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section>
        <h3 className="font-semibold">Crop water use</h3>
        <p className="mt-1 text-sm text-ink-2">Reference evapotranspiration (ET₀) from the weather, and the crop's actual use: ET₀ × crop coefficient, reduced under stress.</p>
        <div className="mt-3 h-64">
          <ResponsiveContainer>
            <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis dataKey="day" tickFormatter={shortDate} minTickGap={28} tick={{ fontSize: 12, fill: "var(--ink-3)" }} />
              <YAxis tick={{ fontSize: 12, fill: "var(--ink-3)" }} label={{ value: "mm/day", angle: -90, position: "insideLeft", fontSize: 12, fill: "var(--ink-3)" }} />
              <Tooltip labelFormatter={(d) => shortDate(String(d))} contentStyle={{ fontSize: 13, background: "var(--surface)", border: "1px solid var(--line)" }} />
              <Legend wrapperStyle={{ fontSize: 13 }} />
              <Line dataKey="et0" name="ET₀ (reference)" stroke="var(--ink-3)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
              <Line dataKey="etc" name="Crop water use" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section>
        <h3 className="font-semibold">Season so far</h3>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-4 text-sm sm:grid-cols-4">
          {[
            ["Crop water need (ETc)", mm(s.etc_mm)],
            ["Actual use (ETa)", mm(s.eta_mm)],
            ["Rain", `${mm(s.rain_mm)} (${mm(s.effective_rain_mm)} useful)`],
            ["Irrigation applied", `${mm(s.irrigation_gross_mm)} in ${s.irrigation_events ?? 0} events`],
            ["Lost below the roots", mm(s.deep_percolation_mm)],
            ["Days with water stress", String(s.stress_days ?? 0)],
            ["Expected yield", typeof s.relative_yield === "number" ? `${Math.round(s.relative_yield * 100)}% of potential` : "Not estimated for this crop"],
            ["Soil and roots", `${wb.soil.name}, ${wb.root_depth_m} m roots`],
          ].map(([k, v]) => (
            <div key={k}><dt className="text-ink-3">{k}</dt><dd className="tabular-nums">{v}</dd></div>
          ))}
        </dl>
      </section>

      <details className="text-sm">
        <summary className="cursor-pointer text-ink-2">Method and assumptions</summary>
        <p className="mt-2 text-ink-2">Weather: {wb.source_description}.</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-2">{wb.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
      </details>
    </div>
  );
}
