import { useMemo, useRef, useState } from "react";
import type { LitEntry } from "@/api/client";
import {
  useCreateLit,
  useDeleteLit,
  useImportLit,
  useLitMatrix,
  useLitPrisma,
  useLitVocabulary,
  useLiterature,
  useUpdateLit,
} from "@/api/hooks";
import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { cn } from "@/lib/cn";

type Tab = "papers" | "screening" | "matrix";
type DimKey = "layers" | "techniques" | "metrics" | "domains" | "evaluation" | "datasets" | "tags";

const DIM_LABELS: Record<DimKey, string> = {
  layers: "Computing layers",
  techniques: "Techniques",
  metrics: "Metrics",
  domains: "Agricultural domains",
  evaluation: "Evaluation method",
  datasets: "Datasets",
  tags: "Other tags",
};
const DIMS = Object.keys(DIM_LABELS) as DimKey[];

const SOURCES = ["Scopus", "Web of Science", "IEEE Xplore", "ACM Digital Library", "ScienceDirect", "Google Scholar", "Snowballing"];
const EXCLUSION_REASONS = [
  "Not fog, edge or cloud computing",
  "Not agriculture or IoT",
  "No evaluation",
  "Not peer reviewed",
  "Full text not available",
  "Duplicate study",
];

const STAGE_TONE: Record<string, string> = {
  identified: "bg-[var(--st-planned-bg)] text-[var(--st-planned)]",
  screened_out: "bg-danger-bg text-danger",
  full_text: "bg-[var(--st-integration-bg)] text-[var(--st-integration)]",
  excluded: "bg-danger-bg text-danger",
  included: "bg-[var(--st-implemented-bg)] text-[var(--st-implemented)]",
};

function shortAuthors(authors: string): string {
  const names = authors.split(/\s+and\s+/).filter(Boolean);
  if (names.length === 0) return "Unknown authors";
  const last = (n: string) => (n.includes(",") ? n.split(",")[0] : n.split(" ").at(-1) ?? n).trim();
  return names.length > 2 ? `${last(names[0])} et al.` : names.map(last).join(" and ");
}

export default function Literature() {
  const [tab, setTab] = useState<Tab>("papers");
  const { data: entries = [] } = useLiterature();
  const { data: vocab } = useLitVocabulary();
  const stages = vocab?.stages ?? {};

  return (
    <>
      <PageHeader
        title="Literature matrix"
        lead="Import references from Zotero or a database search, screen them with the PRISMA 2020 flow, classify the included studies and find the combinations nobody has studied yet."
        actions={<ExportLinks />}
      />
      <div role="tablist" aria-label="Literature views" className="mb-6 flex gap-1 border-b border-line">
        {(
          [
            ["papers", `Papers (${entries.length})`],
            ["screening", "Screening"],
            ["matrix", "Gap matrix"],
          ] as const
        ).map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={cn("-mb-px border-b-2 px-3 py-2 text-sm font-medium",
              tab === id ? "border-accent text-ink" : "border-transparent text-ink-3 hover:text-ink")}>
            {label}
          </button>
        ))}
      </div>
      {tab === "papers" && <Papers entries={entries} stages={stages} suggestions={vocab?.suggestions ?? {}} />}
      {tab === "screening" && <Screening entries={entries} />}
      {tab === "matrix" && <GapMatrix entries={entries} />}
    </>
  );
}

function ExportLinks() {
  const link = "rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-ink hover:bg-surface-2";
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-ink-3">Included studies:</span>
      <a className={link} href="/api/literature/export/bib?stage=included" download>BibTeX</a>
      <a className={link} href="/api/literature/export/tex?stage=included" download>LaTeX table</a>
      <a className={link} href="/api/literature/export/csv" download title="Every paper, with screening decisions and tags">CSV (all)</a>
    </div>
  );
}

// --- Papers ---------------------------------------------------------------------------------------

function Papers({ entries, stages, suggestions }: {
  entries: LitEntry[]; stages: Record<string, string>; suggestions: Record<string, string[]>;
}) {
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter((e) => (!stage || e.stage === stage) &&
      (!q || `${e.title} ${e.authors} ${e.venue} ${e.keywords} ${DIMS.map((d) => e[d].join(" ")).join(" ")}`.toLowerCase().includes(q)));
  }, [entries, query, stage]);
  const current = entries.find((e) => e.id === selected) ?? null;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
      <section className="min-w-0">
        <ImportBar onAdd={() => setAdding(true)} />
        {adding && <AddPaper onDone={() => setAdding(false)} />}
        <div className="mt-5 mb-3 flex flex-wrap gap-2">
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search titles, authors, tags…" aria-label="Search papers"
            className="min-w-56 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm" />
          <select value={stage} onChange={(e) => setStage(e.target.value)} aria-label="Filter by stage"
            className="rounded-lg border border-line bg-surface px-3 py-2 text-sm">
            <option value="">All stages</option>
            {Object.entries(stages).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        {entries.length === 0 ? (
          <div className="rounded-xl border border-dashed border-line p-8 text-sm text-ink-2">
            <p className="font-medium text-ink">No papers yet.</p>
            <p className="mt-1">In Zotero, select a collection, choose <em>Export Collection</em> and pick BibTeX or CSL JSON, then import the file above.
              Scopus, Web of Science and IEEE Xplore can also export BibTeX directly. Duplicates across files are detected by DOI and title.</p>
          </div>
        ) : (
          <ul className="divide-y divide-line border-y border-line">
            {shown.map((e) => (
              <li key={e.id}>
                <button type="button" onClick={() => setSelected(e.id)}
                  className={cn("flex w-full items-start gap-3 px-2 py-3 text-left hover:bg-surface-2", selected === e.id && "bg-accent-soft")}>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium leading-snug">{e.title}</div>
                    <p className="mt-0.5 truncate text-xs text-ink-3">
                      {shortAuthors(e.authors)}{e.year ? `, ${e.year}` : ""}{e.venue ? `. ${e.venue}` : ""}
                    </p>
                  </div>
                  <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-xs", STAGE_TONE[e.stage])}>{stages[e.stage] ?? e.stage}</span>
                </button>
              </li>
            ))}
            {shown.length === 0 && <li className="py-6 text-sm text-ink-3">No papers match this search.</li>}
          </ul>
        )}
      </section>
      <aside className="lg:sticky lg:top-4 lg:self-start">
        {current ? <Editor key={current.id} entry={current} stages={stages} suggestions={suggestions} onClose={() => setSelected(null)} />
          : <p className="rounded-xl border border-line p-5 text-sm text-ink-3">Select a paper to screen it, tag it and write notes.</p>}
      </aside>
    </div>
  );
}

function ImportBar({ onAdd }: { onAdd: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [source, setSource] = useState("Scopus");
  const imp = useImportLit();
  const r = imp.data;
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-xs text-ink-3">Where the file came from (for the PRISMA diagram)</span>
          <input list="lit-sources" value={source} onChange={(e) => setSource(e.target.value)}
            className="w-56 rounded-lg border border-line bg-surface px-3 py-2" />
          <datalist id="lit-sources">{SOURCES.map((s) => <option key={s} value={s} />)}</datalist>
        </label>
        <input ref={fileRef} type="file" accept=".bib,.bibtex,.json,.txt" className="hidden" aria-label="Reference file"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) imp.mutate({ file: f, source }); e.target.value = ""; }} />
        <Button variant="primary" disabled={imp.isPending} onClick={() => fileRef.current?.click()}>
          {imp.isPending ? "Importing…" : "Import .bib or .json"}
        </Button>
        <Button onClick={onAdd}>Add a paper by hand</Button>
      </div>
      {imp.error && <p className="mt-3 text-sm text-danger">{imp.error.message}</p>}
      {r && (
        <p className="mt-3 text-sm text-ink-2" role="status">
          Added {r.added} {r.added === 1 ? "paper" : "papers"}. {r.duplicates > 0 && `Skipped ${r.duplicates} already in the matrix. `}
          {r.failed > 0 && <span className="text-danger">{r.failed} entries could not be read. </span>}
        </p>
      )}
    </div>
  );
}

function AddPaper({ onDone }: { onDone: () => void }) {
  const create = useCreateLit();
  const [f, setF] = useState({ title: "", authors: "", year: "", venue: "", doi: "" });
  const field = (k: keyof typeof f, label: string, hint?: string) => (
    <label className="text-sm">
      <span className="mb-1 block text-xs text-ink-3">{label}</span>
      <input value={f[k]} placeholder={hint} onChange={(e) => setF({ ...f, [k]: e.target.value })}
        className="w-full rounded-lg border border-line bg-surface px-3 py-2" />
    </label>
  );
  return (
    <form className="mt-3 grid gap-3 rounded-xl border border-line bg-surface p-4 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate({ ...f, year: f.year ? Number(f.year) : null }, { onSuccess: onDone });
      }}>
      <div className="sm:col-span-2">{field("title", "Title")}</div>
      {field("authors", "Authors", "Sharma, Priya and Li, Wei")}
      {field("year", "Year")}
      {field("venue", "Journal or conference")}
      {field("doi", "DOI")}
      {create.error && <p className="text-sm text-danger sm:col-span-2">{create.error.message}</p>}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" variant="primary" disabled={!f.title.trim() || create.isPending}>Add paper</Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

function ChipInput({ label, values, suggestions, onChange }: {
  label: string; values: string[]; suggestions: string[]; onChange: (v: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const id = `chips-${label.replace(/\W+/g, "-").toLowerCase()}`;
  const add = (raw: string) => {
    const v = raw.trim().replace(/,$/, "");
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  };
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs text-ink-3">{label}</label>
      <div className="flex flex-wrap gap-1.5 rounded-lg border border-line bg-surface p-1.5">
        {values.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-md bg-accent-soft px-2 py-0.5 text-xs">
            {v}
            <button type="button" aria-label={`Remove ${v}`} className="text-ink-3 hover:text-ink" onClick={() => onChange(values.filter((x) => x !== v))}>×</button>
          </span>
        ))}
        <input id={id} list={`${id}-list`} value={draft} placeholder={values.length ? "" : "Type or pick…"}
          className="min-w-24 flex-1 bg-transparent px-1 py-0.5 text-sm outline-none"
          onChange={(e) => {
            const v = e.target.value;
            if (v.endsWith(",") || suggestions.includes(v)) add(v); else setDraft(v);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); add(draft); }
            if (e.key === "Backspace" && !draft && values.length) onChange(values.slice(0, -1));
          }}
          onBlur={() => draft && add(draft)} />
        <datalist id={`${id}-list`}>{suggestions.filter((s) => !values.includes(s)).map((s) => <option key={s} value={s} />)}</datalist>
      </div>
    </div>
  );
}

function Editor({ entry, stages, suggestions, onClose }: {
  entry: LitEntry; stages: Record<string, string>; suggestions: Record<string, string[]>; onClose: () => void;
}) {
  const update = useUpdateLit();
  const del = useDeleteLit();
  const [draft, setDraft] = useState(entry);
  const [confirm, setConfirm] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(entry);
  const save = () => {
    const patch: Record<string, unknown> = {};
    for (const k of ["stage", "exclusion_reason", "relevance", "contribution", "limitations", "notes", ...DIMS] as const)
      if (JSON.stringify(draft[k]) !== JSON.stringify(entry[k])) patch[k] = draft[k];
    update.mutate({ id: entry.id, patch });
  };
  const text = (k: "contribution" | "limitations" | "notes", label: string) => (
    <label className="block text-sm">
      <span className="mb-1 block text-xs text-ink-3">{label}</span>
      <textarea rows={2} value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
        className="w-full rounded-lg border border-line bg-surface px-3 py-2" />
    </label>
  );
  return (
    <div className="space-y-4 rounded-xl border border-line bg-surface p-5">
      <div className="flex items-start gap-2">
        <h2 className="flex-1 font-semibold leading-snug">{entry.title}</h2>
        <button type="button" onClick={onClose} aria-label="Close" className="text-ink-3 hover:text-ink">×</button>
      </div>
      <p className="text-xs text-ink-3">
        {entry.authors || "Unknown authors"}{entry.year ? ` (${entry.year})` : ""}. Cite as <code>{entry.bibtex_key}</code>.
        {entry.doi && <>{" "}<a className="text-accent hover:underline" href={`https://doi.org/${entry.doi}`} target="_blank" rel="noreferrer">Open the paper</a></>}
      </p>
      {entry.abstract && <details className="text-sm text-ink-2"><summary className="cursor-pointer text-ink">Abstract</summary><p className="mt-2">{entry.abstract}</p></details>}
      <div className="grid grid-cols-[minmax(0,1fr)_7.5rem] gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-xs text-ink-3">Stage</span>
          <select value={draft.stage} onChange={(e) => setDraft({ ...draft, stage: e.target.value })}
            className="w-full rounded-lg border border-line bg-surface px-2 py-2">
            {Object.entries(stages).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-xs text-ink-3">Relevance</span>
          <select value={draft.relevance} onChange={(e) => setDraft({ ...draft, relevance: Number(e.target.value) })}
            className="w-full rounded-lg border border-line bg-surface px-2 py-2">
            {["Not rated", "Low", "Medium", "High"].map((l, i) => <option key={l} value={i}>{l}</option>)}
          </select>
        </label>
      </div>
      {(draft.stage === "excluded" || draft.stage === "screened_out") && (
        <label className="block text-sm">
          <span className="mb-1 block text-xs text-ink-3">Reason for exclusion</span>
          <input list="lit-reasons" value={draft.exclusion_reason} onChange={(e) => setDraft({ ...draft, exclusion_reason: e.target.value })}
            className="w-full rounded-lg border border-line bg-surface px-3 py-2" />
          <datalist id="lit-reasons">{EXCLUSION_REASONS.map((r) => <option key={r} value={r} />)}</datalist>
        </label>
      )}
      {DIMS.map((d) => (
        <ChipInput key={d} label={DIM_LABELS[d]} values={draft[d]} suggestions={suggestions[d] ?? []}
          onChange={(v) => setDraft({ ...draft, [d]: v })} />
      ))}
      {text("contribution", "Main contribution")}
      {text("limitations", "Limitations")}
      {text("notes", "Notes")}
      {update.error && <p className="text-sm text-danger">{update.error.message}</p>}
      <div className="flex items-center gap-2">
        <Button variant="primary" disabled={!dirty || update.isPending} onClick={save}>{update.isPending ? "Saving…" : "Save changes"}</Button>
        {dirty && <Button onClick={() => setDraft(entry)}>Discard</Button>}
        <Button variant="ghost" className="ml-auto" onClick={() => setConfirm(true)}>Delete</Button>
      </div>
      <ConfirmDialog open={confirm} title="Delete this paper?" body="It is removed from the matrix and from the PRISMA counts."
        confirmLabel="Delete paper" onCancel={() => setConfirm(false)}
        onConfirm={() => { del.mutate(entry.id); setConfirm(false); onClose(); }} />
    </div>
  );
}

// --- Screening ------------------------------------------------------------------------------------

function Screening({ entries }: { entries: LitEntry[] }) {
  const { data: p } = useLitPrisma();
  const update = useUpdateLit();
  const [reason, setReason] = useState("");
  const titleQueue = entries.filter((e) => e.stage === "identified");
  const fullQueue = entries.filter((e) => e.stage === "full_text");
  const [phase, setPhase] = useState<"title" | "full">("title");
  const queue = phase === "title" ? titleQueue : fullQueue;
  const paper = queue[0];
  const decide = (stage: string, exclusion_reason = "") => {
    if (!paper) return;
    update.mutate({ id: paper.id, patch: { stage, exclusion_reason } });
    setReason("");
  };

  return (
    <div className="grid gap-8 lg:grid-cols-[22rem_minmax(0,1fr)]">
      <section aria-label="PRISMA 2020 flow">
        <h2 className="mb-1 font-semibold">PRISMA 2020 flow</h2>
        <p className="mb-4 text-xs text-ink-3">Counts update as you screen. Copy them into the PRISMA diagram in your paper.</p>
        {p && (
          <ol className="space-y-2 text-sm">
            <FlowBox title="Records identified" n={p.identified}
              detail={Object.entries(p.by_source).map(([s, n]) => `${s}: ${n}`).join(", ") || "Import a file to begin"} />
            <FlowBox title="Duplicates removed" n={p.duplicates_removed} side />
            <FlowBox title="Records screened (title and abstract)" n={p.screened}
              detail={p.awaiting_screening ? `${p.awaiting_screening} still to screen` : undefined} />
            <FlowBox title="Excluded at screening" n={p.excluded_screening} side />
            <FlowBox title="Full texts assessed" n={p.assessed_full_text}
              detail={p.awaiting_full_text ? `${p.awaiting_full_text} waiting for full-text reading` : undefined} />
            <FlowBox title="Full texts excluded" n={p.excluded_full_text} side
              detail={Object.entries(p.exclusion_reasons).map(([r, n]) => `${r}: ${n}`).join("; ") || undefined} />
            <FlowBox title="Studies included in the review" n={p.included} strong />
          </ol>
        )}
      </section>
      <section>
        <div className="mb-4 flex flex-wrap gap-2">
          <Button variant={phase === "title" ? "primary" : "secondary"} onClick={() => setPhase("title")}>
            Title and abstract ({titleQueue.length})
          </Button>
          <Button variant={phase === "full" ? "primary" : "secondary"} onClick={() => setPhase("full")}>
            Full text ({fullQueue.length})
          </Button>
        </div>
        {!paper ? (
          <p className="rounded-xl border border-dashed border-line p-8 text-sm text-ink-2">
            {phase === "title" ? "Nothing left to screen. Papers you keep move to the full-text queue." : "No papers are waiting for full-text assessment."}
          </p>
        ) : (
          <article className="rounded-xl border border-line bg-surface p-6">
            <p className="text-xs text-ink-3">{queue.length} remaining</p>
            <h3 className="mt-1 text-lg font-semibold leading-snug">{paper.title}</h3>
            <p className="mt-1 text-sm text-ink-3">{shortAuthors(paper.authors)}{paper.year ? `, ${paper.year}` : ""}{paper.venue ? `. ${paper.venue}` : ""}</p>
            <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-2">{paper.abstract || "No abstract in the imported record."}</p>
            {paper.doi && <a className="mt-3 inline-block text-sm text-accent hover:underline" href={`https://doi.org/${paper.doi}`} target="_blank" rel="noreferrer">Open the paper</a>}
            <div className="mt-6 flex flex-wrap items-end gap-2 border-t border-line pt-4">
              {phase === "title" ? (
                <>
                  <Button variant="primary" disabled={update.isPending} onClick={() => decide("full_text")}>Keep for full text</Button>
                  <Button disabled={update.isPending} onClick={() => decide("screened_out", reason)}>Exclude</Button>
                </>
              ) : (
                <>
                  <Button variant="primary" disabled={update.isPending} onClick={() => decide("included")}>Include in review</Button>
                  <label className="text-sm">
                    <span className="mb-1 block text-xs text-ink-3">Reason (PRISMA needs one for full-text exclusions)</span>
                    <input list="lit-reasons-screen" value={reason} onChange={(e) => setReason(e.target.value)}
                      className="w-64 rounded-lg border border-line bg-surface px-3 py-2" />
                    <datalist id="lit-reasons-screen">{EXCLUSION_REASONS.map((r) => <option key={r} value={r} />)}</datalist>
                  </label>
                  <Button disabled={update.isPending || !reason.trim()} onClick={() => decide("excluded", reason.trim())}>Exclude</Button>
                </>
              )}
            </div>
          </article>
        )}
      </section>
    </div>
  );
}

function FlowBox({ title, n, detail, side, strong }: { title: string; n: number; detail?: string; side?: boolean; strong?: boolean }) {
  return (
    <li className={cn("rounded-lg border px-3 py-2", side ? "ml-8 border-dashed border-line text-ink-2" : "border-line bg-surface",
      strong && "border-[var(--st-implemented)] bg-[var(--st-implemented-bg)]")}>
      <div className="flex items-baseline justify-between gap-3">
        <span>{title}</span>
        <span className="text-base font-semibold tabular-nums">{n}</span>
      </div>
      {detail && <p className="mt-0.5 text-xs text-ink-3">{detail}</p>}
    </li>
  );
}

// --- Gap matrix -----------------------------------------------------------------------------------

function GapMatrix({ entries }: { entries: LitEntry[] }) {
  const [rows, setRows] = useState<DimKey>("techniques");
  const [cols, setCols] = useState<DimKey>("layers");
  const [stage, setStage] = useState("included");
  const [cell, setCell] = useState<string | null>(null);
  const { data: m } = useLitMatrix(rows, cols, stage);
  const max = Math.max(1, ...(m?.counts.flat() ?? [0]));
  const byId = useMemo(() => new Map(entries.map((e) => [e.id, e])), [entries]);
  const cellPapers = cell ? (m?.papers[cell] ?? []).map((id) => byId.get(id)).filter(Boolean) as LitEntry[] : [];
  const gaps = m ? m.counts.flat().filter((c) => c === 0).length : 0;

  const select = (value: string, onChange: (v: DimKey) => void, label: string) => (
    <label className="text-sm">
      <span className="mb-1 block text-xs text-ink-3">{label}</span>
      <select value={value} onChange={(e) => { onChange(e.target.value as DimKey); setCell(null); }}
        className="rounded-lg border border-line bg-surface px-3 py-2">
        {DIMS.map((d) => <option key={d} value={d}>{DIM_LABELS[d]}</option>)}
      </select>
    </label>
  );

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end gap-3">
        {select(rows, setRows, "Rows")}
        {select(cols, setCols, "Columns")}
        <label className="text-sm">
          <span className="mb-1 block text-xs text-ink-3">Papers counted</span>
          <select value={stage} onChange={(e) => { setStage(e.target.value); setCell(null); }}
            className="rounded-lg border border-line bg-surface px-3 py-2">
            <option value="included">Included studies</option>
            <option value="included,full_text">Included and awaiting full text</option>
            <option value="">Every paper</option>
          </select>
        </label>
      </div>
      {!m || m.rows.length === 0 || m.cols.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line p-8 text-sm text-ink-2">
          The matrix fills in as you tag papers. Open a paper in the Papers tab and add values for
          {" "}<strong>{DIM_LABELS[rows].toLowerCase()}</strong> and <strong>{DIM_LABELS[cols].toLowerCase()}</strong>.
          {m && m.total === 0 && stage === "included" && " No papers are marked as included yet; try counting every paper."}
        </p>
      ) : (
        <>
          <p className="mb-3 text-sm text-ink-2">
            {m.total} papers. Each cell counts papers tagged with both values; a paper can count in several cells.
            {gaps > 0 && ` ${gaps} empty ${gaps === 1 ? "combination is" : "combinations are"} marked as possible gaps.`}
          </p>
          <div className="overflow-x-auto">
            <table className="border-separate border-spacing-1 text-sm">
              <thead>
                <tr>
                  <th />
                  {m.cols.map((c) => <th key={c} scope="col" className="max-w-28 px-1 pb-1 text-left align-bottom text-xs font-medium text-ink-2">{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {m.rows.map((r, ri) => (
                  <tr key={r}>
                    <th scope="row" className="max-w-56 pr-2 text-left text-xs font-medium text-ink-2">{r}</th>
                    {m.cols.map((c, ci) => {
                      const n = m.counts[ri][ci];
                      const key = `${r}|${c}`;
                      return (
                        <td key={c} className="p-0">
                          <button type="button" disabled={n === 0} onClick={() => setCell(key)}
                            aria-label={`${r}, ${c}: ${n} ${n === 1 ? "paper" : "papers"}`}
                            className={cn("h-10 w-16 rounded-md text-sm tabular-nums",
                              n === 0 ? "border border-dashed border-line text-ink-3" : "font-medium hover:ring-2 hover:ring-accent",
                              cell === key && "ring-2 ring-ink")}
                            style={n > 0 ? {
                              background: `color-mix(in oklab, var(--accent) ${15 + (70 * n) / max}%, var(--surface))`,
                              color: n / max > 0.5 ? "var(--accent-ink)" : "var(--ink)",
                            } : undefined}>
                            {n === 0 ? "gap" : n}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {cell && (
            <section className="mt-6">
              <h3 className="mb-2 font-semibold">{cell.replace("|", " and ")}</h3>
              <ul className="divide-y divide-line border-y border-line text-sm">
                {cellPapers.map((e) => (
                  <li key={e.id} className="py-2">
                    <span className="font-medium">{e.title}</span>
                    <span className="text-ink-3"> {shortAuthors(e.authors)}{e.year ? `, ${e.year}` : ""}. <code>{e.bibtex_key}</code></span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <p className="mt-6 max-w-prose text-xs text-ink-3">
            An empty cell means none of the counted papers was tagged with that pair. It is a gap in your sample, which suggests
            but does not prove a gap in the field: confirm it with a targeted search before claiming it in a paper.
          </p>
        </>
      )}
    </div>
  );
}
