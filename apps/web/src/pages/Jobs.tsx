import { Link } from "react-router-dom";
import { useCancelJob, useJobs, usePlugins } from "@/api/hooks";
import { Button } from "@/components/Button";
import { PageHeader } from "@/components/PageHeader";
import { ProgressBar } from "@/components/ProgressBar";
import { OriginBadge } from "@/components/StatusBadge";
import { formatDuration, formatTime } from "@/lib/format";

export default function Jobs() {
  const { data: jobs, isLoading } = useJobs();
  const { data: plugins } = usePlugins();
  const cancel = useCancelJob();
  const name = (id: string) => plugins?.find((p) => p.id === id)?.name ?? id;

  return (
    <>
      <PageHeader
        title="Jobs"
        lead="Long-running work runs in the background. Progress updates live, and you can leave this page while jobs run."
      />
      {isLoading && <p className="text-sm text-ink-3">Loading jobs…</p>}
      {jobs?.length === 0 && (
        <p className="text-sm text-ink-2">
          No jobs yet. Start one from a runnable algorithm in the{" "}
          <Link to="/algorithms" className="text-accent hover:underline">
            algorithm catalogue
          </Link>
          .
        </p>
      )}
      {jobs && jobs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-ink-3">
              <tr className="border-b border-line">
                <th className="py-2 pr-4 font-normal">What</th>
                <th className="py-2 pr-4 font-normal">Status</th>
                <th className="w-56 py-2 pr-4 font-normal">Progress</th>
                <th className="py-2 pr-4 font-normal">Started</th>
                <th className="py-2 pr-4 font-normal">Took</th>
                <th className="py-2 font-normal">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {jobs.map((j) => {
                const active = j.status === "running" || j.status === "queued";
                return (
                  <tr key={j.id} className="align-middle">
                    <td className="py-3 pr-4">
                      <Link to={`/jobs/${j.id}`} className="font-medium hover:text-accent">
                        {name(j.plugin_id)}
                      </Link>
                      <div className="mt-0.5 flex items-center gap-2">
                        <OriginBadge origin={j.data_origin} />
                      </div>
                    </td>
                    <td className="py-3 pr-4 capitalize">{j.status}</td>
                    <td className="py-3 pr-4">
                      <ProgressBar value={j.progress} status={j.status} />
                      <div className="mt-1 truncate text-xs text-ink-3">{j.error ?? j.message}</div>
                    </td>
                    <td className="py-3 pr-4 whitespace-nowrap text-ink-2 tabular-nums">
                      {formatTime(j.started_at ?? j.created_at)}
                    </td>
                    <td className="py-3 pr-4 text-ink-2 tabular-nums">{formatDuration(j.started_at, j.finished_at)}</td>
                    <td className="py-3 text-right">
                      {active && (
                        <Button variant="ghost" onClick={() => cancel.mutate(j.id)} disabled={cancel.isPending}>
                          Cancel
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
