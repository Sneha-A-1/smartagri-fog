import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { elevationAt, placeSearch, useCreateFarm, useFarms } from "@/api/hooks";
import { Button } from "@/components/Button";
import { FarmMap } from "@/components/FarmMap";
import { PageHeader } from "@/components/PageHeader";
import { useUi } from "@/stores/ui";

const DEFAULT_CENTER: [number, number] = [22.5, 79]; // India

export default function Farms() {
  const { data: farms, isLoading } = useFarms();
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", region: "", latitude: "", longitude: "", elevation_m: "" });
  const [flyTo, setFlyTo] = useState<number[][] | null>(null);
  const [elevNote, setElevNote] = useState("");

  // Place the farm, then look up its elevation unless the user typed one.
  const locate = (la: number, lo: number, fly: boolean, region?: string) => {
    setForm((f) => ({ ...f, latitude: la.toFixed(5), longitude: lo.toFixed(5), region: region && !f.region ? region : f.region }));
    if (fly) setFlyTo([[lo, la]]);
    setElevNote("Looking up elevation…");
    elevationAt(la, lo)
      .then((r) => { setForm((f) => ({ ...f, elevation_m: String(r.elevation_m) })); setElevNote("Filled in from a terrain model; change it if you know better."); })
      .catch(() => setElevNote("Couldn't look it up; type an estimate."));
  };
  const create = useCreateFarm();
  const navigate = useNavigate();
  const projectId = useUi((s) => s.currentProjectId);

  const lat = Number(form.latitude);
  const lon = Number(form.longitude);
  const located = form.latitude !== "" && form.longitude !== "" && Math.abs(lat) <= 90 && Math.abs(lon) <= 180;
  const points = (farms ?? []).map((f) => ({ id: f.id, name: f.name, lat: f.latitude, lon: f.longitude,
    label: `${f.name}: ${f.fields.length} field${f.fields.length === 1 ? "" : "s"}` }));
  if (creating && located) points.push({ id: "new", name: form.name || "New farm", lat, lon, label: "New farm" });
  const fields = (farms ?? []).flatMap((f) => f.fields.filter((x) => x.boundary.length >= 3).map((x) => ({ id: x.id, name: x.name, boundary: x.boundary })));
  const fit = (farms ?? []).map((f) => [f.longitude, f.latitude]);

  const input = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm";
  return (
    <>
      <PageHeader
        title="Farms"
        lead="Your farms and their fields. A field holds its boundary, crop and sowing date, soil and irrigation method, which the irrigation advice and the digital twin use."
        actions={!creating && <Button variant="primary" onClick={() => setCreating(true)}>New farm</Button>}
      />
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <FarmMap
          center={DEFAULT_CENTER}
          zoom={farms?.length ? 12 : 5}
          points={points}
          fields={fields}
          fitTo={creating ? flyTo : fit.length ? fit : null}
          onPointClick={(id) => id !== "new" && navigate(`/farms/${id}`)}
          onMapClick={creating ? (la, lo) => locate(la, lo, false) : undefined}
          className="h-[34rem] overflow-hidden rounded-xl border border-line"
        />
        <aside>
          {creating ? (
            <form
              className="space-y-3 rounded-xl border border-line bg-surface p-5"
              onSubmit={(e) => {
                e.preventDefault();
                create.mutate(
                  { name: form.name.trim(), region: form.region, latitude: lat, longitude: lon, elevation_m: Number(form.elevation_m) || 0, project_id: projectId },
                  { onSuccess: (farm) => navigate(`/farms/${farm.id}`) },
                );
              }}
            >
              <h2 className="font-semibold">New farm</h2>
              <p className="text-sm text-ink-2">Find the village or town, then click the exact spot on the satellite map.</p>
              <PlaceSearch onPick={(p) => locate(p.latitude, p.longitude, true, p.name.split(",").slice(0, 2).join(",").trim())} />
              <button type="button" className="text-sm text-accent hover:underline"
                onClick={() => navigator.geolocation?.getCurrentPosition(
                  (pos) => locate(pos.coords.latitude, pos.coords.longitude, true),
                  () => setElevNote("Your browser didn't share its location; search or click the map instead."),
                )}>
                Use my current location
              </button>
              <label className="block text-sm">
                <span className="mb-1 block text-xs text-ink-3">Name</span>
                <input className={input} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-xs text-ink-3">Village, district or region</span>
                <input className={input} value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-sm">
                  <span className="mb-1 block text-xs text-ink-3">Latitude</span>
                  <input className={input} inputMode="decimal" value={form.latitude} onChange={(e) => setForm({ ...form, latitude: e.target.value })} required />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-xs text-ink-3">Longitude</span>
                  <input className={input} inputMode="decimal" value={form.longitude} onChange={(e) => setForm({ ...form, longitude: e.target.value })} required />
                </label>
              </div>
              <label className="block text-sm">
                <span className="mb-1 block text-xs text-ink-3">Elevation (m above sea level)</span>
                <input className={input} inputMode="decimal" value={form.elevation_m} onChange={(e) => setForm({ ...form, elevation_m: e.target.value })} />
                <span className="mt-1 block text-xs text-ink-3">{elevNote || "Used for air pressure in the evapotranspiration formula; an estimate is fine."}</span>
              </label>
              {create.error && <p className="text-sm text-danger">{create.error.message}</p>}
              <div className="flex gap-2">
                <Button type="submit" variant="primary" disabled={!form.name.trim() || !located || create.isPending}>Create farm</Button>
                <Button onClick={() => setCreating(false)}>Cancel</Button>
              </div>
            </form>
          ) : (
            <>
              {isLoading && <p className="text-sm text-ink-3">Loading…</p>}
              {farms?.length === 0 && (
                <div className="rounded-xl border border-dashed border-line p-5 text-sm text-ink-2">
                  <p className="font-medium text-ink">No farms yet.</p>
                  <p className="mt-1">Create a farm, then draw its fields on the satellite map.</p>
                </div>
              )}
              <ul className="divide-y divide-line border-y border-line">
                {farms?.map((f) => (
                  <li key={f.id}>
                    <Link to={`/farms/${f.id}`} className="block py-3 hover:text-accent">
                      <div className="font-medium">{f.name}</div>
                      <p className="mt-0.5 text-xs text-ink-3">
                        {f.region && `${f.region}. `}
                        {f.fields.length} field{f.fields.length === 1 ? "" : "s"}, {f.total_area_ha.toFixed(2)} ha.
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          )}
        </aside>
      </div>
    </>
  );
}

type Place = { name: string; latitude: number; longitude: number; kind: string };

function PlaceSearch({ onPick }: { onPick: (p: Place) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Place[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const search = () => {
    if (q.trim().length < 2) return;
    setBusy(true);
    setError("");
    placeSearch(q.trim())
      .then((r) => setResults(r))
      .catch((e: Error) => { setResults(null); setError(e.message); })
      .finally(() => setBusy(false));
  };
  return (
    <div>
      <div className="flex gap-2">
        <input
          className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
          placeholder="Village, town or district"
          aria-label="Search for a place"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); search(); } }}
        />
        <Button onClick={search} disabled={busy || q.trim().length < 2}>{busy ? "Searching…" : "Find"}</Button>
      </div>
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      {results && results.length === 0 && <p className="mt-1 text-xs text-ink-3">No places found. Try adding the district or state.</p>}
      {results && results.length > 0 && (
        <ul className="mt-2 max-h-48 divide-y divide-line overflow-y-auto rounded-lg border border-line text-sm">
          {results.map((p) => (
            <li key={`${p.latitude},${p.longitude}`}>
              <button type="button" className="w-full px-3 py-2 text-left hover:bg-surface-2" onClick={() => { onPick(p); setResults(null); }}>
                {p.name}
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-[11px] text-ink-3">Search by OpenStreetMap Nominatim.</p>
    </div>
  );
}
