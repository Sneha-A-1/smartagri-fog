import { Link } from "react-router-dom";
import { useHealth, useJobs, usePlugins, useSystemInfo } from "@/api/hooks";
import { ProgressBar } from "@/components/ProgressBar";
import { OriginBadge, StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";
import { CURRENT_PHASE, PHASES } from "@/lib/roadmap";
import { MODULES } from "@/modules/registry";

const STATUS_ORDER = ["implemented", "simulated", "needs-integration", "planned"] as const;
const BAR: Record<string, string> = {
  implemented: "bg-[var(--st-implemented)]",
  simulated: "bg-[var(--st-simulated)]",
  "needs-integration": "bg-[var(--st-integration)]",
  planned: "bg-[var(--st-planned-bg)]",
};

export default function Overview() {
  const { data: plugins } = usePlugins();
  const { data: jobs } = useJobs();
  const { data: info } = useSystemInfo();
  const { data: health, isError } = useHealth();

  const pageCounts = countBy(MODULES.map((m) => m.status));
  const pluginCounts = countBy(plugins?.map((p) => p.status) ?? []);

  return (
    <div className="space-y-12">
      <section aria-labelledby="build-heading">
        <h1 id="build-heading" className="text-[1.65rem] font-semibold tracking-[-0.01em]">
          SmartAgri-Fog is in Phase {CURRENT_PHASE}: {PHASES[CURRENT_PHASE].name.toLowerCase()}
        </h1>
        <p className="mt-2 max-w-2xl text-ink-2">
          The simulator and baseline schedulers run now, from the algorithm catalogue. Pages and algorithms that don't
          exist yet are listed with the phase they arrive in, and none of them produce results.
        </p>

        <ol className="mt-8 grid grid-cols-4 gap-px overflow-hidden rounded-xl border border-line bg-line lg:grid-cols-8">
          {PHASES.map((p) => {
            const state = p.n < CURRENT_PHASE ? "done" : p.n === CURRENT_PHASE ? "now" : "later";
            return (
              <li
                key={p.n}
                className={cn("bg-surface p-3", state === "now" && "bg-accent-soft")}
                aria-current={state === "now" ? "step" : undefined}
              >
                <div className={cn("text-xs tabular-nums", state === "now" ? "text-accent" : "text-ink-3")}>
                  Phase {p.n}
                  {state === "now" && " (now)"}
                </div>
                <div className={cn("mt-1 text-sm leading-snug", state === "later" ? "text-ink-2" : "font-medium")}>
                  {p.name}
                </div>
              </li>
            );
          })}
        </ol>

        <div className="mt-6 grid gap-6 md:grid-cols-2">
          <Composition title="Pages" total={MODULES.length} counts={pageCounts} />
          <Composition title="Algorithms and generators" total={plugins?.length ?? 0} counts={pluginCounts} />
        </div>
      </section>

      <section className="grid gap-10 lg:grid-cols-[1.4fr_1fr]">
        <div>
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-semibold">Recent jobs</h2>
            <Link to="/jobs" className="text-sm text-accent hover:underline">
              All jobs
            </Link>
          </div>
          {jobs && jobs.length > 0 ? (
            <ul className="mt-3 divide-y divide-line border-y border-line">
              {jobs.slice(0, 5).map((j) => (
                <li key={j.id} className="py-3">
                  <Link to={`/jobs/${j.id}`} className="flex items-center gap-3 text-sm hover:text-accent">
                    <span className="min-w-0 flex-1 truncate">{plugins?.find((p) => p.id === j.plugin_id)?.name ?? j.plugin_id}</span>
                    <OriginBadge origin={j.data_origin} />
                    <span className="w-24 text-right text-xs text-ink-3">{j.status}</span>
                  </Link>
                  {(j.status === "running" || j.status === "queued") && (
                    <ProgressBar value={j.progress} status={j.status} className="mt-2" />
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-ink-2">
              No jobs yet. Open the{" "}
              <Link className="text-accent hover:underline" to="/algorithms/data_generator%3Asoil_moisture_demo">
                soil-moisture demo
              </Link>{" "}
              and start one to see live progress.
            </p>
          )}
        </div>

        <div>
          <h2 className="text-lg font-semibold">System</h2>
          <dl className="mt-3 divide-y divide-line border-y border-line text-sm">
            <Row label="API">{isError ? <span className="text-danger">Not reachable</span> : (health?.status ?? "…")}</Row>
            <Row label="Database">{health?.database ?? "…"}</Row>
            <Row label="Mode">{health?.local_mode ? "Local, single user" : "Multi-user"}</Row>
            <Row label="Job workers">{info?.job_workers ?? "…"}</Row>
            <Row label="Results folder">
              <span className="break-all">{info?.results_dir ?? "…"}</span>
            </Row>
            <Row label="Versions">
              API {health?.version ?? "…"}, core {health?.core_version ?? "…"}
            </Row>
          </dl>
          {info && info.plugin_load_errors.length > 0 && (
            <p className="mt-3 text-sm text-danger">
              {info.plugin_load_errors.length} plugin package(s) failed to load. See Settings for details.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function Composition({ title, total, counts }: { title: string; total: number; counts: Record<string, number> }) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium">{title}</span>
        <span className="text-ink-3 tabular-nums">{total}</span>
      </div>
      <div className="mt-2 flex h-2.5 overflow-hidden rounded-full bg-surface-2" aria-hidden>
        {STATUS_ORDER.map((s) =>
          counts[s] ? <div key={s} className={BAR[s]} style={{ width: `${(counts[s] / Math.max(total, 1)) * 100}%` }} /> : null,
        )}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
        {STATUS_ORDER.filter((s) => counts[s]).map((s) => (
          <li key={s} className="flex items-center gap-1.5">
            <StatusBadge status={s} /> <span className="tabular-nums">{counts[s]}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2">
      <dt className="text-ink-3">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function countBy(values: string[]): Record<string, number> {
  return values.reduce<Record<string, number>>((acc, v) => ({ ...acc, [v]: (acc[v] ?? 0) + 1 }), {});
}
