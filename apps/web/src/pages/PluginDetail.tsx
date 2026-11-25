import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { usePlugin, useStartJob } from "@/api/hooks";
import { Button } from "@/components/Button";
import { type FieldErrors, type JsonSchema, SchemaForm } from "@/components/SchemaForm";
import { StatusBadge } from "@/components/StatusBadge";
import { useUi } from "@/stores/ui";

export default function PluginDetail() {
  const { pluginId = "" } = useParams();
  const navigate = useNavigate();
  const { data: plugin, isLoading, error } = usePlugin(pluginId);
  const mode = useUi((s) => s.mode);
  const projectId = useUi((s) => s.currentProjectId);
  const startJob = useStartJob();
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (plugin) setValues(plugin.default_params);
  }, [plugin]);

  // Live validation against the backend's own rules, so the form never disagrees with the API.
  useEffect(() => {
    if (!plugin?.runnable) return;
    const timer = setTimeout(async () => {
      const { data } = await api.POST("/api/plugins/{plugin_id}/validate", {
        params: { path: { plugin_id: plugin.id } },
        body: { params: values },
      });
      if (!data) return;
      const fieldErrors: FieldErrors = {};
      const general: string[] = [];
      for (const e of data.errors ?? []) {
        const loc = (e as { loc?: unknown[] }).loc;
        const field = String(loc?.[0] ?? "");
        if (field && field in (plugin.params_schema as JsonSchema).properties!) fieldErrors[field] = String(e.msg);
        else general.push(String(e.msg).replace(/^Value error, /, ""));
      }
      setErrors(fieldErrors);
      setFormError(general.length ? general.join("; ") : null);
    }, 300);
    return () => clearTimeout(timer);
  }, [values, plugin]);

  if (isLoading) return <p className="text-sm text-ink-3">Loading…</p>;
  if (error || !plugin)
    return (
      <p className="text-sm text-danger">
        {error?.message ?? "Not found."} <Link to="/algorithms" className="text-accent">Back to the catalogue</Link>
      </p>
    );

  const invalid = Object.keys(errors).length > 0 || Boolean(formError);
  const start = () =>
    startJob.mutate(
      { plugin_id: plugin.id, params: values, project_id: projectId },
      { onSuccess: (job) => navigate(`/jobs/${job.id}`) },
    );

  const meta: [string, string[]][] = [
    ["Runs on", plugin.layers],
    ["Agricultural use", plugin.agri_applications],
    ["Inputs", plugin.inputs],
    ["Outputs", plugin.outputs],
    ["Metrics", plugin.metrics],
    ["References", plugin.references],
  ];

  return (
    <article>
      <Link to="/algorithms" className="text-sm text-ink-3 hover:text-accent">
        Algorithm catalogue
      </Link>
      <header className="mt-2 mb-8 flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="flex flex-wrap items-center gap-3 text-[1.65rem] font-semibold tracking-[-0.01em]">
            {plugin.name} <StatusBadge status={plugin.status} />
          </h1>
          <p className="mt-2 text-ink-2">{plugin.summary}</p>
          {plugin.description && <p className="mt-2 text-sm text-ink-2">{plugin.description}</p>}
          <p className="mt-3 text-xs text-ink-3">
            {plugin.id}, version {plugin.version}, from {plugin.source}
          </p>
        </div>
      </header>

      <div className="grid gap-10 lg:grid-cols-[1fr_18rem]">
        <section>
          {plugin.runnable ? (
            <>
              <h2 className="mb-4 text-lg font-semibold">Parameters</h2>
              <SchemaForm
                schema={plugin.params_schema as JsonSchema}
                values={values}
                onChange={setValues}
                errors={errors}
                showAdvanced={mode === "researcher"}
              />
              {formError && <p className="mt-4 text-sm text-danger">{formError}</p>}
              {startJob.error && <p className="mt-4 text-sm text-danger">{startJob.error.message}</p>}
              <div className="mt-6 flex gap-2">
                <Button variant="primary" disabled={invalid || startJob.isPending} onClick={start}>
                  {startJob.isPending ? "Starting…" : "Start job"}
                </Button>
                <Button variant="ghost" onClick={() => setValues(plugin.default_params)}>
                  Reset to defaults
                </Button>
              </div>
            </>
          ) : (
            <div className="rounded-xl border border-dashed border-line p-6">
              <h2 className="font-semibold">
                {plugin.phase !== null ? `Arrives in Phase ${plugin.phase}` : "Not available yet"}
              </h2>
              <p className="mt-1 text-sm text-ink-2">
                This entry describes a planned algorithm. It has no implementation yet, so it can't be run and no
                results exist for it.
              </p>
            </div>
          )}
        </section>

        <aside>
          <dl className="space-y-4 text-sm">
            {meta
              .filter(([, v]) => v.length)
              .map(([label, v]) => (
                <div key={label}>
                  <dt className="text-ink-3">{label}</dt>
                  <dd className="mt-0.5">{v.join(", ")}</dd>
                </div>
              ))}
          </dl>
        </aside>
      </div>
    </article>
  );
}
