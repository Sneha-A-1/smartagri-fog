import { Download, FileSpreadsheet, FileText, Images, Package, Sigma } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useReportPreview, useReports } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { OriginBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";
import { formatTime } from "@/lib/format";

const DOWNLOADS: { fmt: string; label: string; detail: string; icon: typeof Download }[] = [
  { fmt: "pdf", label: "PDF report", detail: "Summary, tables, figures and parameters", icon: FileText },
  { fmt: "latex", label: "LaTeX for Overleaf", detail: "main.tex, booktabs tables, vector figures", icon: Sigma },
  { fmt: "xlsx", label: "Excel workbook", detail: "Every table with CIs, plus raw runs", icon: FileSpreadsheet },
  { fmt: "figures", label: "Figures", detail: "PDF, SVG and 300-dpi PNG", icon: Images },
  { fmt: "bundle", label: "Reproducibility bundle", detail: "All of the above, data, versions and re-run command", icon: Package },
];

export default function Reports() {
  const [search, setSearch] = useSearchParams();
  const { data: list, isLoading } = useReports();
  const jobId = search.get("job") ?? list?.[0]?.job_id ?? "";
  const { data: rep, isLoading: loadingPreview, error } = useReportPreview(jobId);
  const [openTables, setOpenTables] = useState<Record<string, boolean>>({});

  return (
    <div>
      <PageHeader
        title="Reports"
        lead="Turn any finished job into material for a paper: a PDF report, LaTeX tables and figures for Overleaf, an Excel workbook, or a reproducibility bundle with the exact command to re-run it."
      />
      <div className="grid gap-10 lg:grid-cols-[18rem_1fr]">
        <aside>
          <h2 className="text-sm font-semibold">Finished jobs</h2>
          {isLoading && <p className="mt-3 text-sm text-ink-3">Loading…</p>}
          {list && list.length === 0 && (
            <p className="mt-3 text-sm text-ink-2">
              No finished jobs yet. Run a simulation, an experiment or the{" "}
              <Link to="/evaluation" className="text-accent hover:underline">AURA evaluation</Link> first.
            </p>
          )}
          <ul className="mt-3 space-y-1">
            {list?.map((j) => (
              <li key={j.job_id}>
                <button
                  onClick={() => setSearch({ job: j.job_id })}
                  aria-current={j.job_id === jobId}
                  className={cn(
                    "w-full rounded-lg px-3 py-2 text-left text-sm",
                    j.job_id === jobId ? "bg-accent-soft text-ink" : "text-ink-2 hover:bg-surface-2",
                  )}
                >
                  <span className="block font-medium">{j.title}</span>
                  <span className="block text-xs text-ink-3">
                    {j.finished_at ? formatTime(j.finished_at) : ""}
                    {j.dedicated_layout ? "" : " · basic layout"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="min-w-0">
          {jobId && loadingPreview && <p className="text-sm text-ink-3">Building the preview…</p>}
          {error && <p className="text-sm text-danger">{error.message}</p>}
          {rep && (
            <div className="space-y-10">
              <div>
                <div className="flex flex-wrap items-center gap-3">
                  <h2 className="text-xl font-semibold">{rep.title}</h2>
                  <OriginBadge origin={rep.data_origin} />
                </div>
                {rep.subtitle && <p className="mt-1 text-sm text-ink-3">{rep.subtitle}</p>}
                <p className="mt-1 text-xs text-ink-3">
                  From <Link to={`/jobs/${rep.job_id}`} className="text-accent hover:underline">job {rep.job_id.slice(0, 8)}</Link> ({rep.plugin_id})
                </p>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {DOWNLOADS.map(({ fmt, label, detail, icon: Icon }) => (
                  <a key={fmt} href={`/api/reports/${rep.job_id}/export/${fmt}`} download
                    className="flex items-start gap-3 rounded-xl border border-line bg-surface p-4 hover:border-accent focus-visible:outline-2 focus-visible:outline-accent">
                    <Icon className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden />
                    <span>
                      <span className="block text-sm font-medium">{label}</span>
                      <span className="block text-xs text-ink-3">{detail}</span>
                    </span>
                  </a>
                ))}
              </div>
              <p className="-mt-6 text-xs text-ink-3">
                The first download of a large result can take a few seconds while the figures are drawn.
              </p>

              <div className="max-w-3xl">
                <h3 className="font-semibold">Summary</h3>
                <div className="mt-2 space-y-2 text-sm text-ink-2">
                  {rep.summary.filter(Boolean).map((s) => <p key={s}>{s}</p>)}
                </div>
                {rep.caveats.length > 0 && (
                  <>
                    <h3 className="mt-5 font-semibold">Caveats</h3>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
                      {rep.caveats.map((c) => <li key={c}>{c}</li>)}
                    </ul>
                  </>
                )}
              </div>

              {rep.figures.length > 0 && (
                <div>
                  <h3 className="font-semibold">Figures ({rep.figures.length})</h3>
                  <p className="mt-1 text-xs text-ink-3">As they will appear in the paper: two-column sizing, Times-like fonts, colour-blind-safe colours with hatching for greyscale print.</p>
                  <div className="mt-4 grid gap-6 xl:grid-cols-2">
                    {rep.figures.map((f) => (
                      <figure key={f.key} className="rounded-xl border border-line bg-white p-3">
                        <img src={`/api/reports/${rep.job_id}/figure/${f.key}.svg`} alt={f.caption} loading="lazy" className="w-full" />
                        <figcaption className="mt-2 text-xs text-gray-600">
                          <span className="font-mono">{f.key}</span>: {f.caption}
                        </figcaption>
                      </figure>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <h3 className="font-semibold">Tables ({rep.tables.length})</h3>
                <div className="mt-3 space-y-3">
                  {rep.tables.map((t, ti) => {
                    const open = openTables[t.key] ?? ti === 0;
                    return (
                      <div key={t.key} className="rounded-xl border border-line">
                        <button className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm"
                          aria-expanded={open} onClick={() => setOpenTables((o) => ({ ...o, [t.key]: !open }))}>
                          <span><span className="font-mono text-xs text-ink-3">{t.key}</span> {t.caption}</span>
                          <span className="text-ink-3">{open ? "Hide" : "Show"}</span>
                        </button>
                        {open && (
                          <div className="overflow-x-auto border-t border-line px-4 py-3">
                            <table className="w-full text-xs">
                              <thead className="text-left text-ink-3">
                                <tr className="border-b border-line">
                                  {t.columns.map((c, i) => (
                                    <th key={c} className={cn("py-1.5 pr-3 font-normal", t.numeric[i] && "text-right")}>{c}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-line">
                                {t.rows.map((row, ri) => (
                                  <tr key={ri} className={ri === t.highlight_row ? "font-semibold" : undefined}>
                                    {row.map((v, i) => (
                                      <td key={i} className={cn("py-1.5 pr-3", t.numeric[i] && "text-right tabular-nums")}>{v}</td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                            {t.notes && <p className="mt-2 text-xs text-ink-3">{t.notes}</p>}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
