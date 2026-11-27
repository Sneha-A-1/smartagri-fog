import { useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { DatasetT } from "@/api/client";
import {
  useDataset,
  useDatasetMetrics,
  useDatasetPreview,
  useDatasetValidation,
  useDatasets,
  useDeleteDataset,
  useUpdateDataset,
  useUploadDataset,
} from "@/api/hooks";
import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { OriginBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";

const kb = (n: number) => (n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
const fmtNum = (v: unknown) => (typeof v === "number" ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toPrecision(3)) : String(v ?? "–"));

export default function DataAcquisition() {
  const [params, setParams] = useSearchParams();
  const { data: datasets } = useDatasets();
  const selected = params.get("dataset") ?? "";
  const select = (id: string) => { const p = new URLSearchParams(params); if (id) p.set("dataset", id); else p.delete("dataset"); setParams(p, { replace: true }); };

  return (
    <>
      <PageHeader
        title="Data acquisition"
        lead="Bring your own data: upload sensor or weather records as CSV, Excel or JSON, check their quality, tell the platform what each column means, and run them through the data retrieval framework."
      />
      <div className="grid gap-8 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <aside className="space-y-4">
          <Upload onUploaded={select} />
          {datasets && datasets.length > 0 && (
            <ul className="divide-y divide-line border-y border-line text-sm">
              {datasets.map((d) => (
                <li key={d.id}>
                  <button type="button" onClick={() => select(d.id)} className={cn("w-full px-2 py-2.5 text-left hover:bg-surface-2", selected === d.id && "bg-accent-soft")}>
                    <span className="block truncate font-medium">{d.name}</span>
                    <span className="block text-xs text-ink-3">{d.format.toUpperCase()}, {d.rows.toLocaleString()} rows, {d.origin}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>
        <section className="min-w-0">
          {selected ? <DatasetDetail key={selected} id={selected} onDeleted={() => select("")} /> : (
            <div className="rounded-xl border border-dashed border-line p-8 text-sm text-ink-2">
              <p className="font-medium text-ink">{datasets?.length ? "Select a dataset." : "No datasets yet."}</p>
              <p className="mt-1">A good file has one row per reading time and one column per measurement, or one row per reading with columns for the time, the sensor, the variable and the value.</p>
              <p className="mt-2">Examples: a weather station's export, a data logger's CSV, soil-moisture probe records, or data from IMD or another agency.</p>
            </div>
          )}
        </section>
      </div>
    </>
  );
}

function Upload({ onUploaded }: { onUploaded: (id: string) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const upload = useUploadDataset();
  const [file, setFile] = useState<File | null>(null);
  const [form, setForm] = useState({ name: "", origin: "real", source_note: "" });
  const input = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm";
  return (
    <form className="space-y-3 rounded-xl border border-line bg-surface p-4" onSubmit={(e) => {
      e.preventDefault();
      if (file) upload.mutate({ file, ...form }, { onSuccess: (d) => { setFile(null); setForm({ name: "", origin: "real", source_note: "" }); onUploaded(d.id); } });
    }}>
      <h2 className="font-semibold">Upload a dataset</h2>
      <input ref={ref} type="file" accept=".csv,.txt,.tsv,.xlsx,.xlsm,.json" className="hidden" aria-label="Dataset file"
        onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); if (f && !form.name) setForm({ ...form, name: f.name.replace(/\.[^.]+$/, "") }); e.target.value = ""; }} />
      <Button onClick={() => ref.current?.click()} className="w-full">{file ? `${file.name} (${kb(file.size)})` : "Choose a CSV, Excel or JSON file"}</Button>
      {file && (
        <>
          <label className="block text-sm"><span className="mb-1 block text-xs text-ink-3">Name</span>
            <input className={input} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          <fieldset className="text-sm">
            <legend className="mb-1 text-xs text-ink-3">Where the data comes from</legend>
            {[["real", "Measured (real sensors or stations)"], ["synthetic", "Simulated or invented"], ["derived", "Computed from real data"]].map(([k, l]) => (
              <label key={k} className="flex items-center gap-2 py-0.5"><input type="radio" checked={form.origin === k} onChange={() => setForm({ ...form, origin: k })} />{l}</label>
            ))}
          </fieldset>
          <label className="block text-sm"><span className="mb-1 block text-xs text-ink-3">Source and licence (for citing it)</span>
            <textarea rows={2} className={input} placeholder="e.g. IMD station Pusa, daily data 2024, obtained on request" value={form.source_note} onChange={(e) => setForm({ ...form, source_note: e.target.value })} />
          </label>
          {upload.error && <p className="text-sm text-danger">{upload.error.message}</p>}
          <Button type="submit" variant="primary" className="w-full" disabled={upload.isPending}>{upload.isPending ? "Uploading…" : "Upload"}</Button>
        </>
      )}
      <p className="text-[11px] text-ink-3">Up to 50 MB and 200,000 rows. The original file is kept unchanged in the platform's data folder.</p>
    </form>
  );
}

function DatasetDetail({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const { data: d, error } = useDataset(id);
  const update = useUpdateDataset();
  const del = useDeleteDataset();
  const [confirm, setConfirm] = useState(false);
  const [offset, setOffset] = useState(0);
  const { data: preview } = useDatasetPreview(id, offset);
  if (error) return <p className="text-sm text-danger">{error.message}</p>;
  if (!d) return <p className="text-sm text-ink-3">Loading…</p>;

  return (
    <div className="space-y-8">
      <header>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">{d.name}</h2>
            <p className="mt-1 text-sm text-ink-2">
              {d.filename}, {d.format.toUpperCase()}{d.sheet ? `, sheet ${d.sheet}` : ""}, {d.rows.toLocaleString()} rows, {d.columns.length} columns, {kb(d.size_bytes)}.
              Uploaded {new Date(d.created_at).toLocaleDateString()}.
            </p>
            {d.source_note && <p className="mt-1 text-sm text-ink-3">Source: {d.source_note}</p>}
            <p className="mt-1 text-xs text-ink-3">SHA-256 {d.sha256.slice(0, 16)}… (identifies this exact file in a paper's data statement)</p>
          </div>
          <OriginBadge origin={d.origin} />
        </div>
        {d.sheets.length > 1 && (
          <label className="mt-3 block text-sm"><span className="mr-2 text-ink-3">Sheet</span>
            <select className="rounded-lg border border-line bg-surface px-2 py-1 text-sm" value={d.sheet ?? ""} onChange={(e) => update.mutate({ id, patch: { sheet: e.target.value } })}>
              {d.sheets.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        )}
        {d.warnings.length > 0 && <ul className="mt-3 rounded-lg bg-surface-2 p-3 text-sm text-ink-2">{d.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
        <div className="mt-4 flex flex-wrap gap-2">
          <Link to={`/data/retrieval?dataset=${d.id}`} className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-[var(--accent-ink)] hover:opacity-90">Run the retrieval framework</Link>
          <a href={`/api/datasets/${d.id}/tidy.csv`} className="rounded-lg border border-line bg-surface px-3.5 py-2 text-sm font-medium hover:bg-surface-2" download>Export tidy CSV</a>
          <a href={`/api/datasets/${d.id}/download`} className="rounded-lg border border-line bg-surface px-3.5 py-2 text-sm font-medium hover:bg-surface-2" download>Original file</a>
          <Button variant="ghost" className="ml-auto" onClick={() => setConfirm(true)}>Delete</Button>
        </div>
      </header>

      <section>
        <h3 className="font-semibold">Columns</h3>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead className="text-left text-ink-3">
              <tr className="border-b border-line">
                <th className="py-2 pr-3 font-normal">Column</th><th className="py-2 pr-3 font-normal">Type</th>
                <th className="py-2 pr-3 text-right font-normal">Missing</th><th className="py-2 pr-3 text-right font-normal">Min</th>
                <th className="py-2 pr-3 text-right font-normal">Max</th><th className="py-2 pr-3 text-right font-normal">Mean</th>
                <th className="py-2 font-normal">Examples</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {d.columns.map((c) => (
                <tr key={String(c.name)}>
                  <td className="py-1.5 pr-3 font-medium">{String(c.name)}</td>
                  <td className="py-1.5 pr-3">{String(c.type)}{c.format && c.format !== "native" ? <span className="text-xs text-ink-3"> {String(c.format)}</span> : null}</td>
                  <td className={cn("py-1.5 pr-3 text-right tabular-nums", Number(c.missing) > 0 && "text-danger")}>{Number(c.missing).toLocaleString()}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{c.type === "datetime" ? String(c.min ?? "–").replace("T", " ").slice(0, 16) : fmtNum(c.min)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{c.type === "datetime" ? String(c.max ?? "–").replace("T", " ").slice(0, 16) : fmtNum(c.max)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{c.type === "number" ? fmtNum(c.mean) : ""}</td>
                  <td className="max-w-48 truncate py-1.5 text-ink-3">{(c.examples as string[]).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <MappingEditor dataset={d} />

      {preview && (
        <section>
          <div className="flex items-baseline justify-between">
            <h3 className="font-semibold">Rows</h3>
            <div className="flex items-center gap-2 text-sm">
              <span className="text-ink-3">{preview.offset + 1}–{Math.min(preview.offset + preview.rows.length, preview.total)} of {preview.total.toLocaleString()}</span>
              <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</Button>
              <Button disabled={offset + 25 >= preview.total} onClick={() => setOffset(offset + 25)}>Next</Button>
            </div>
          </div>
          <div className="mt-2 overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-xs">
              <thead className="bg-surface-2 text-left text-ink-3"><tr>{preview.columns.map((c) => <th key={c} className="px-2 py-1.5 font-medium whitespace-nowrap">{c}</th>)}</tr></thead>
              <tbody className="divide-y divide-line">
                {preview.rows.map((r, i) => <tr key={preview.offset + i}>{r.map((v, j) => <td key={j} className="px-2 py-1 whitespace-nowrap tabular-nums">{v === null ? <span className="text-ink-3">–</span> : String(v)}</td>)}</tr>)}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <ConfirmDialog open={confirm} title={`Delete "${d.name}"?`} body="The dataset and its stored file are removed from the platform." confirmLabel="Delete dataset"
        onCancel={() => setConfirm(false)} onConfirm={() => { del.mutate(d.id, { onSuccess: onDeleted }); setConfirm(false); }} />
    </div>
  );
}

type MappingT = { time_column: string | null; source_column: string | null; metrics: Record<string, string>; metric_column: string | null; value_column: string | null; soil_stress_theta: number | null };

function MappingEditor({ dataset }: { dataset: DatasetT }) {
  const { data: metricInfo } = useDatasetMetrics();
  const update = useUpdateDataset();
  const initial = dataset.mapping as unknown as MappingT;
  const [m, setM] = useState<MappingT>(initial);
  const [long, setLong] = useState(Boolean(initial.metric_column));
  const version = JSON.stringify(dataset.mapping);
  const { data: report, error } = useDatasetValidation(dataset.id, version);
  const cols = dataset.columns.map((c) => ({ name: String(c.name), type: String(c.type) }));
  const norm = (x: MappingT) => JSON.stringify([x.time_column, x.source_column, Object.entries(x.metrics ?? {}).sort(), x.metric_column, x.value_column, x.soil_stress_theta]);
  const dirty = norm(m) !== norm(initial);
  const sel = "w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm";
  const colSelect = (value: string | null, onChange: (v: string | null) => void, filter?: (t: string) => boolean, none = "None") => (
    <select className={sel} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{none}</option>
      {cols.filter((c) => !filter || filter(c.type)).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
    </select>
  );

  return (
    <section className="space-y-4">
      <div>
        <h3 className="font-semibold">What the columns mean</h3>
        <p className="mt-1 text-sm text-ink-2">The platform guessed this from the column names and types. Check it, then save; the quality report and the retrieval framework use it.</p>
      </div>
      <div className="grid gap-4 rounded-xl border border-line bg-surface p-4 sm:grid-cols-2">
        <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">Date and time</span>
          {colSelect(m.time_column, (v) => setM({ ...m, time_column: v }), undefined, "Choose a column")}
        </label>
        <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">Sensor or station name (if the file has several)</span>
          {colSelect(m.source_column, (v) => setM({ ...m, source_column: v }))}
        </label>
        <div className="flex gap-4 text-sm sm:col-span-2">
          <label className="flex items-center gap-2"><input type="radio" checked={!long} onChange={() => { setLong(false); setM({ ...m, metric_column: null, value_column: null }); }} />One column per measurement</label>
          <label className="flex items-center gap-2"><input type="radio" checked={long} onChange={() => { setLong(true); setM({ ...m, metrics: {} }); }} />A variable column and a value column</label>
        </div>
        {long ? (
          <>
            <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">Variable name column</span>{colSelect(m.metric_column, (v) => setM({ ...m, metric_column: v }))}</label>
            <label className="text-sm"><span className="mb-1 block text-xs text-ink-3">Value column</span>{colSelect(m.value_column, (v) => setM({ ...m, value_column: v }), (t) => t === "number")}</label>
            <p className="text-xs text-ink-3 sm:col-span-2">Variable names that match the platform's metrics ({Object.keys(metricInfo?.metrics ?? {}).join(", ")}) get validation and alert rules.</p>
          </>
        ) : (
          <div className="space-y-2 sm:col-span-2">
            {cols.filter((c) => c.type === "number").map((c) => (
              <label key={c.name} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] items-center gap-3 text-sm">
                <span className="truncate">{c.name}</span>
                <select className={sel} value={m.metrics[c.name] ?? ""} onChange={(e) => {
                  const metrics = { ...m.metrics };
                  if (e.target.value) metrics[c.name] = e.target.value; else delete metrics[c.name];
                  setM({ ...m, metrics });
                }}>
                  <option value="">Not used</option>
                  {Object.entries(metricInfo?.metrics ?? {}).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </label>
            ))}
            {cols.every((c) => c.type !== "number") && <p className="text-sm text-ink-3">No numeric columns were found.</p>}
          </div>
        )}
        {(Object.values(m.metrics).includes("soil_moisture_m3m3") || long) && (
          <label className="text-sm sm:col-span-2"><span className="mb-1 block text-xs text-ink-3">Soil moisture at which the crop starts water stress (m³/m³, optional)</span>
            <input type="number" step="0.01" className={sel} value={m.soil_stress_theta ?? ""} onChange={(e) => setM({ ...m, soil_stress_theta: e.target.value === "" ? null : Number(e.target.value) })} />
            <span className="mt-1 block text-xs text-ink-3">Without it, soil readings are validated and reduced but raise no stress alerts. The Smart irrigation page shows a field's threshold.</span>
          </label>
        )}
        <div className="flex items-center gap-3 sm:col-span-2">
          <Button variant="primary" disabled={!dirty || update.isPending} onClick={() => update.mutate({ id: dataset.id, patch: { mapping: m } })}>Save mapping</Button>
          {update.error && <span className="text-sm text-danger">{update.error.message}</span>}
        </div>
      </div>

      <div>
        <h3 className="font-semibold">Data quality</h3>
        {error && <p className="mt-2 text-sm text-danger">{error.message}</p>}
        {report && (
          <div className="mt-2 space-y-3 text-sm">
            {report.problems.length > 0 && <ul className="rounded-lg bg-danger-bg p-3 text-danger">{report.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
            {report.duplicate_rows > 0 && <p className="text-ink-2">{report.duplicate_rows} rows are exact duplicates of another row.</p>}
            {report.series.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[44rem] text-sm">
                  <thead className="text-left text-ink-3">
                    <tr className="border-b border-line">
                      <th className="py-2 pr-3 font-normal">Series</th><th className="py-2 pr-3 font-normal">Period</th>
                      <th className="py-2 pr-3 text-right font-normal">Readings</th><th className="py-2 pr-3 text-right font-normal">Interval</th>
                      <th className="py-2 pr-3 text-right font-normal">Missing</th><th className="py-2 pr-3 text-right font-normal">Gaps</th>
                      <th className="py-2 pr-3 text-right font-normal">Repeated times</th><th className="py-2 text-right font-normal">Out of range</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {report.series.map((s) => (
                      <tr key={`${s.source}-${s.metric}`}>
                        <td className="py-1.5 pr-3">{String(s.source)}, {String(s.metric)}{!s.known_metric && <span className="text-xs text-ink-3"> (no rules)</span>}</td>
                        <td className="py-1.5 pr-3 whitespace-nowrap text-ink-2">{String(s.start ?? "").slice(0, 10)} to {String(s.end ?? "").slice(0, 10)}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{Number(s.points).toLocaleString()}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{s.interval_min === null ? "–" : `${fmtNum(s.interval_min)} min`}</td>
                        <td className={cn("py-1.5 pr-3 text-right tabular-nums", Number(s.missing) > 0 && "text-danger")}>{String(s.missing)}</td>
                        <td className={cn("py-1.5 pr-3 text-right tabular-nums", Number(s.gaps) > 0 && "text-danger")}>{String(s.gaps)}</td>
                        <td className={cn("py-1.5 pr-3 text-right tabular-nums", Number(s.duplicate_times) > 0 && "text-danger")}>{String(s.duplicate_times)}</td>
                        <td className={cn("py-1.5 text-right tabular-nums", Number(s.out_of_range) > 0 && "text-danger")}>{String(s.out_of_range)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-1 text-xs text-ink-3">A gap is a pause longer than three times the usual interval. Out of range uses the physical limits of the retrieval framework.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
