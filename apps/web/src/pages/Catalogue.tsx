import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { Plugin } from "@/api/client";
import { usePlugins } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";

/** Display order follows the research spine: scheduling first, supporting methods after. */
const KIND_LABELS: Record<string, string> = {
  simulation: "Simulation and experiments",
  scheduler: "Complete schedulers",
  placement: "Placement policies",
  queue_discipline: "Queue disciplines",
  optimizer: "Optimisation",
  data_generator: "Data generators",
  data_source: "Data sources",
  pipeline_stage: "Data pipeline",
  preprocessor: "Preprocessing",
  anomaly_detector: "Anomaly detection",
  classifier: "Classification",
  regressor: "Regression",
  clustering: "Clustering",
  deep_model: "Deep learning",
};

const STATUSES = ["implemented", "simulated", "needs-integration", "planned"];
const KIND_ORDER = Object.keys(KIND_LABELS);

const rank = (kind: string) => {
  const i = KIND_ORDER.indexOf(kind);
  return i === -1 ? KIND_ORDER.length : i;
};

export default function Catalogue() {
  const { data: plugins, isLoading, error } = usePlugins();
  const [query, setQuery] = useState("");
  const [statuses, setStatuses] = useState<Set<string>>(new Set());

  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = (plugins ?? []).filter(
      (p) =>
        (!statuses.size || statuses.has(p.status)) &&
        (!q || `${p.name} ${p.summary} ${p.kind} ${p.tags.join(" ")}`.toLowerCase().includes(q)),
    );
    const byKind = new Map<string, Plugin[]>();
    for (const p of filtered) byKind.set(p.kind, [...(byKind.get(p.kind) ?? []), p]);
    return [...byKind.entries()].sort(([a], [b]) => rank(a) - rank(b));
  }, [plugins, query, statuses]);

  const toggle = (s: string) =>
    setStatuses((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });

  return (
    <>
      <PageHeader
        title="Algorithm catalogue"
        lead="Every algorithm and generator the platform knows about. Runnable ones open a parameter form; planned ones show when they arrive."
      />

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by name, kind or purpose"
          className="w-full max-w-sm rounded-lg border border-line bg-surface px-3 py-2 text-sm"
          aria-label="Filter algorithms"
        />
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={statuses.has(s)}
              onClick={() => toggle(s)}
              className={cn(
                "rounded-full border px-1 py-0.5",
                statuses.has(s) ? "border-accent" : "border-transparent opacity-80 hover:opacity-100",
              )}
            >
              <StatusBadge status={s} />
            </button>
          ))}
        </div>
      </div>

      {isLoading && <p className="text-sm text-ink-3">Loading the catalogue…</p>}
      {error && <p className="text-sm text-danger">Couldn't load the catalogue: {error.message}</p>}
      {!isLoading && grouped.length === 0 && <p className="text-sm text-ink-2">No algorithms match these filters.</p>}

      <div className="space-y-10">
        {grouped.map(([kind, items]) => (
          <section key={kind}>
            <h2 className="mb-2 flex items-baseline gap-2 text-base font-semibold">
              {KIND_LABELS[kind] ?? kind}
              <span className="text-sm font-normal text-ink-3 tabular-nums">{items.length}</span>
            </h2>
            <ul className="divide-y divide-line border-y border-line">
              {items.map((p) => (
                <li key={p.id}>
                  <Link
                    to={`/algorithms/${encodeURIComponent(p.id)}`}
                    className="grid gap-x-4 gap-y-1 py-3 hover:bg-surface sm:grid-cols-[minmax(12rem,16rem)_1fr_auto] sm:items-center sm:px-2"
                  >
                    <span className={cn("font-medium", !p.runnable && "text-ink-2")}>{p.name}</span>
                    <span className="text-sm text-ink-2">{p.summary}</span>
                    <span className="flex items-center gap-3 sm:justify-end">
                      {p.phase !== null && p.status === "planned" && (
                        <span className="text-xs text-ink-3 tabular-nums">Phase {p.phase}</span>
                      )}
                      <StatusBadge status={p.status} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </>
  );
}
