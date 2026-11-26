import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { FarmFieldT } from "@/api/client";
import { useAgroPresets, useCreateField, useDeleteFarm, useDeleteField, useFarm, useUpdateField } from "@/api/hooks";
import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { FarmMap } from "@/components/FarmMap";

export default function FarmDetail() {
  const { farmId = "" } = useParams();
  const { data: farm, isLoading } = useFarm(farmId);
  const createField = useCreateField();
  const delFarm = useDeleteFarm();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<string | null>(null);
  const [drawing, setDrawing] = useState<number[][] | null>(null);
  const [confirm, setConfirm] = useState(false);

  if (isLoading) return <p className="text-sm text-ink-3">Loading…</p>;
  if (!farm) return <p className="text-sm text-danger">Farm not found.</p>;

  const current = farm.fields.find((f) => f.id === selected) ?? null;
  const allPoints = farm.fields.flatMap((f) => f.boundary);
  const finish = () => {
    if (!drawing || drawing.length < 3) return;
    createField.mutate(
      { farmId: farm.id, body: { name: `Field ${farm.fields.length + 1}`, boundary: drawing } },
      { onSuccess: (f) => { setSelected(f.id); setDrawing(null); } },
    );
  };

  return (
    <article>
      <Link to="/farms" className="text-sm text-ink-3 hover:text-accent">Farms</Link>
      <header className="mt-2 mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[1.65rem] leading-tight font-semibold tracking-[-0.01em]">{farm.name}</h1>
          <p className="mt-1 text-sm text-ink-2">
            {farm.region && `${farm.region}. `}
            {farm.latitude.toFixed(4)}, {farm.longitude.toFixed(4)}, {farm.elevation_m} m. {farm.fields.length} field
            {farm.fields.length === 1 ? "" : "s"}, {farm.total_area_ha.toFixed(2)} ha.
          </p>
        </div>
        <div className="flex gap-2">
          <Link to={`/weather?farm=${farm.id}`} className="rounded-lg border border-line bg-surface px-3.5 py-2 text-sm font-medium hover:bg-surface-2">Weather</Link>
          <Button variant="ghost" onClick={() => setConfirm(true)}>Delete farm</Button>
        </div>
      </header>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <section>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {drawing === null ? (
              <Button variant="primary" onClick={() => { setDrawing([]); setSelected(null); }}>Draw a field</Button>
            ) : (
              <>
                <span className="text-sm text-ink-2">
                  Click the field's corners on the map ({drawing.length} so far{drawing.length < 3 ? ", at least 3 needed" : ""}).
                </span>
                <Button variant="primary" disabled={drawing.length < 3 || createField.isPending} onClick={finish}>Finish field</Button>
                <Button disabled={!drawing.length} onClick={() => setDrawing(drawing.slice(0, -1))}>Undo corner</Button>
                <Button variant="ghost" onClick={() => setDrawing(null)}>Cancel</Button>
              </>
            )}
          </div>
          <FarmMap
            center={[farm.latitude, farm.longitude]}
            zoom={16}
            points={[{ id: farm.id, name: farm.name, lat: farm.latitude, lon: farm.longitude }]}
            fields={farm.fields.filter((f) => f.boundary.length >= 3).map((f) => ({ id: f.id, name: f.name, boundary: f.boundary, label: `${f.name}, ${f.area_ha.toFixed(2)} ha` }))}
            selectedFieldId={selected}
            onFieldClick={(id) => drawing === null && setSelected(id)}
            onMapClick={drawing !== null ? (lat, lon) => setDrawing([...drawing, [Number(lon.toFixed(6)), Number(lat.toFixed(6))]]) : undefined}
            drawing={drawing ?? undefined}
            fitTo={allPoints.length ? allPoints : [[farm.longitude, farm.latitude]]}
            className="h-[34rem] overflow-hidden rounded-xl border border-line"
          />
          {createField.error && <p className="mt-2 text-sm text-danger">{createField.error.message}</p>}
        </section>

        <aside className="space-y-4">
          {farm.fields.length === 0 && drawing === null && (
            <p className="rounded-xl border border-dashed border-line p-5 text-sm text-ink-2">
              No fields yet. Click <strong>Draw a field</strong>, then click the corners of a field on the satellite map.
            </p>
          )}
          {farm.fields.length > 0 && (
            <ul className="divide-y divide-line border-y border-line text-sm">
              {farm.fields.map((f) => (
                <li key={f.id}>
                  <button type="button" onClick={() => setSelected(f.id)} className={`flex w-full items-baseline justify-between gap-3 px-2 py-2.5 text-left hover:bg-surface-2 ${selected === f.id ? "bg-accent-soft" : ""}`}>
                    <span className="font-medium">{f.name}</span>
                    <span className="text-xs text-ink-3">{f.area_ha.toFixed(2)} ha, {f.crop}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {current && <FieldEditor key={current.id + current.updated_at} field={current} onDeleted={() => setSelected(null)} />}
        </aside>
      </div>
      <ConfirmDialog open={confirm} title={`Delete "${farm.name}"?`} body="The farm, its fields and its imported weather data are removed."
        confirmLabel="Delete farm" onCancel={() => setConfirm(false)}
        onConfirm={() => delFarm.mutate(farm.id, { onSuccess: () => navigate("/farms") })} />
    </article>
  );
}

function FieldEditor({ field, onDeleted }: { field: FarmFieldT; onDeleted: () => void }) {
  const { data: presets } = useAgroPresets();
  const update = useUpdateField();
  const del = useDeleteField();
  const [confirm, setConfirm] = useState(false);
  const [d, setD] = useState({
    name: field.name, crop: field.crop, sowing_date: field.sowing_date ?? "", soil: field.soil,
    irrigation_method: field.irrigation_method, efficiency: String(Math.round(field.efficiency * 100)),
    rainfed: field.rainfed, root_depth_m: field.root_depth_m?.toString() ?? "",
    stages: field.stages?.join(", ") ?? "", notes: field.notes,
  });
  useEffect(() => update.reset(), [field.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const crop = presets?.crops.find((c) => c.key === d.crop);
  const soil = presets?.soils.find((s) => s.key === d.soil);
  const stages = d.stages.trim() ? d.stages.split(/[,\s]+/).filter(Boolean).map(Number) : null;
  const stagesOk = stages === null || (stages.length === 4 && stages.every((n) => Number.isInteger(n) && n > 0));

  const save = () =>
    update.mutate({
      id: field.id,
      patch: {
        name: d.name, crop: d.crop, sowing_date: d.sowing_date || null, soil: d.soil, irrigation_method: d.irrigation_method,
        efficiency: Number(d.efficiency) / 100, rainfed: d.rainfed, root_depth_m: d.root_depth_m ? Number(d.root_depth_m) : null,
        stages, notes: d.notes,
      },
    });

  const input = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm";
  const label = "mb-1 block text-xs text-ink-3";
  return (
    <div className="space-y-3 rounded-xl border border-line bg-surface p-5">
      <label className="block text-sm"><span className={label}>Field name</span>
        <input className={input} value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm"><span className={label}>Crop</span>
          <select className={input} value={d.crop} onChange={(e) => setD({ ...d, crop: e.target.value })}>
            {presets?.crops.map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
          </select>
        </label>
        <label className="text-sm"><span className={label}>Sowing date</span>
          <input type="date" className={input} value={d.sowing_date} onChange={(e) => setD({ ...d, sowing_date: e.target.value })} />
        </label>
      </div>
      <label className="block text-sm"><span className={label}>Soil texture</span>
        <select className={input} value={d.soil} onChange={(e) => setD({ ...d, soil: e.target.value })}>
          {presets?.soils.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
        </select>
        {soil && <span className="mt-1 block text-xs text-ink-3">Holds about {Math.round(soil.taw_per_m)} mm of usable water per metre of soil.</span>}
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm"><span className={label}>Irrigation method</span>
          <select className={input} value={d.irrigation_method} disabled={d.rainfed}
            onChange={(e) => setD({ ...d, irrigation_method: e.target.value, efficiency: String(Math.round((presets?.irrigation_methods[e.target.value] ?? 0.6) * 100)) })}>
            <option value="surface">Surface (flood, furrow)</option>
            <option value="sprinkler">Sprinkler</option>
            <option value="drip">Drip</option>
          </select>
        </label>
        <label className="text-sm"><span className={label}>Efficiency (%)</span>
          <input className={input} inputMode="numeric" value={d.efficiency} disabled={d.rainfed} onChange={(e) => setD({ ...d, efficiency: e.target.value })} />
        </label>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={d.rainfed} onChange={(e) => setD({ ...d, rainfed: e.target.checked })} />
        Rainfed (no irrigation)
      </label>
      <details className="text-sm">
        <summary className="cursor-pointer text-ink-2">Crop details</summary>
        <div className="mt-3 space-y-3">
          <label className="block"><span className={label}>Root depth (m)</span>
            <input className={input} inputMode="decimal" placeholder={crop ? `${crop.root_depth_m} (crop default)` : ""} value={d.root_depth_m} onChange={(e) => setD({ ...d, root_depth_m: e.target.value })} />
          </label>
          <label className="block"><span className={label}>Growth stages in days: initial, development, mid-season, late</span>
            <input className={input} placeholder={crop ? `${crop.stages.join(", ")} (crop default)` : ""} value={d.stages} onChange={(e) => setD({ ...d, stages: e.target.value })} />
            {!stagesOk && <span className="mt-1 block text-xs text-danger">Give four whole numbers, for example 20, 25, 50, 30.</span>}
            <span className="mt-1 block text-xs text-ink-3">Defaults are typical for India; adjust them for your variety and season.</span>
          </label>
          {crop && (
            <p className="text-xs text-ink-3">
              Crop coefficient {crop.kc_ini} at sowing, {crop.kc_mid} at mid-season and {crop.kc_end} at harvest (FAO-56 Table 12).
              Water stress starts when {Math.round(crop.p * 100)}% of the soil's usable water is used (FAO-56 Table 22).
            </p>
          )}
        </div>
      </details>
      <label className="block text-sm"><span className={label}>Notes</span>
        <textarea rows={2} className={input} value={d.notes} onChange={(e) => setD({ ...d, notes: e.target.value })} />
      </label>
      {update.error && <p className="text-sm text-danger">{update.error.message}</p>}
      {update.isSuccess && <p className="text-sm text-[var(--st-implemented)]" role="status">Saved.</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" disabled={update.isPending || !stagesOk || !d.name.trim()} onClick={save}>Save field</Button>
        {field.sowing_date && <Link to={`/irrigation?field=${field.id}`} className="text-sm text-accent hover:underline">Irrigation advice</Link>}
        <Button variant="ghost" className="ml-auto" onClick={() => setConfirm(true)}>Delete</Button>
      </div>
      <ConfirmDialog open={confirm} title={`Delete "${field.name}"?`} body="The field and its settings are removed." confirmLabel="Delete field"
        onCancel={() => setConfirm(false)} onConfirm={() => { del.mutate(field.id); setConfirm(false); onDeleted(); }} />
    </div>
  );
}
