import { Link } from "react-router-dom";
import { useExperiments } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { ProgressBar } from "@/components/ProgressBar";
import { formatTime } from "@/lib/format";
import { useUi } from "@/stores/ui";

const STATUS_TEXT: Record<string, string> = {
  draft: "Draft",
  queued: "Waiting",
  running: "Running",
  succeeded: "Finished",
  failed: "Failed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
};

export default function Experiments() {
  const { data: experiments, isLoading } = useExperiments();
  const projectId = useUi((s) => s.currentProjectId);
  const shown = (experiments ?? []).filter((e) => !projectId || e.project_id === projectId);

  return (
    <>
      <PageHeader
        title="Experiments"
        lead="An experiment compares algorithms on one scenario over many seeded replications, with significance tests. Its definition is saved so the results can be reproduced exactly."
        actions={
          <Link to="/experiments/new" className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-accent-ink hover:bg-accent-hover">
            New experiment
          </Link>
        }
      />
      {isLoading && <p className="text-sm text-ink-3">Loading…</p>}
      {!isLoading && shown.length === 0 && (
        <p className="text-sm text-ink-2">
          No experiments {projectId ? "in this project " : ""}yet. Create one to compare placement policies with proper
          statistics.
        </p>
      )}
      <ul className="divide-y divide-line border-y border-line">
        {shown.map((e) => (
          <li key={e.id}>
            <Link to={`/experiments/${e.id}`} className="grid gap-x-6 gap-y-1 py-4 hover:bg-surface sm:grid-cols-[1fr_14rem] sm:px-2">
              <div className="min-w-0">
                <div className="font-medium">{e.name}</div>
                {e.objective && <p className="mt-0.5 line-clamp-1 text-sm text-ink-2">{e.objective}</p>}
                <p className="mt-1 text-xs text-ink-3">
                  {e.algorithms.join(", ")}. {e.total_runs} runs. Created {formatTime(e.created_at)}.
                </p>
              </div>
              <div className="self-center text-sm">
                <span className={e.status === "failed" ? "text-danger" : "text-ink-2"}>{STATUS_TEXT[e.status] ?? e.status}</span>
                {(e.status === "running" || e.status === "queued") && <ProgressBar value={e.progress} status={e.status} className="mt-1.5" />}
                {e.status === "succeeded" && e.result_summary && (
                  <span className="block text-xs text-ink-3">
                    Significant differences on {String(e.result_summary.significant_metrics)} headline metrics
                  </span>
                )}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
