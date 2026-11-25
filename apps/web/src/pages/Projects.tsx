import { type FormEvent, useState } from "react";
import type { Project } from "@/api/client";
import { useCreateProject, useDeleteProject, useProjects } from "@/api/hooks";
import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { formatTime } from "@/lib/format";
import { useUi } from "@/stores/ui";

export default function Projects() {
  const { data: projects, isLoading } = useProjects();
  const create = useCreateProject();
  const remove = useDeleteProject();
  const currentProjectId = useUi((s) => s.currentProjectId);
  const set = useUi((s) => s.set);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [seed, setSeed] = useState(42);
  const [toDelete, setToDelete] = useState<Project | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { name: name.trim(), description, default_seed: seed },
      {
        onSuccess: (p) => {
          setName("");
          setDescription("");
          set({ currentProjectId: p.id });
        },
      },
    );
  };

  return (
    <>
      <PageHeader
        title="Projects"
        lead="A project groups the experiments, datasets and results of one study, such as one paper or one crop season."
      />

      <div className="grid gap-12 lg:grid-cols-[1fr_20rem]">
        <section>
          {isLoading && <p className="text-sm text-ink-3">Loading…</p>}
          {projects?.length === 0 && <p className="text-sm text-ink-2">No projects yet. Create your first one.</p>}
          <ul className="divide-y divide-line border-y border-line">
            {projects?.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-4 py-4">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">
                    {p.name}
                    {p.id === currentProjectId && <span className="ml-2 text-xs font-normal text-accent">current</span>}
                  </div>
                  {p.description && <p className="mt-0.5 text-sm text-ink-2">{p.description}</p>}
                  <p className="mt-1 text-xs text-ink-3">
                    Created {formatTime(p.created_at)}. Default seed {p.default_seed}.
                  </p>
                </div>
                {p.id !== currentProjectId && (
                  <Button variant="ghost" onClick={() => set({ currentProjectId: p.id })}>
                    Make current
                  </Button>
                )}
                <Button variant="ghost" onClick={() => setToDelete(p)}>
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        </section>

        <form onSubmit={submit} className="space-y-4">
          <h2 className="text-lg font-semibold">New project</h2>
          <label className="block text-sm">
            <span className="mb-1.5 block font-medium">Name</span>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Kharif paddy 2027"
              className="w-full rounded-lg border border-line bg-surface px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1.5 block font-medium">Description</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-line bg-surface px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1.5 block font-medium">Default random seed</span>
            <input
              type="number"
              min={0}
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 tabular-nums"
            />
            <span className="mt-1 block text-xs text-ink-3">Experiments in this project start from this seed.</span>
          </label>
          {create.error && <p className="text-sm text-danger">{create.error.message}</p>}
          <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
            Create project
          </Button>
        </form>
      </div>

      <ConfirmDialog
        open={toDelete !== null}
        title={`Delete "${toDelete?.name}"?`}
        body="The project is removed. Jobs that belonged to it are kept but no longer linked to a project. This can't be undone."
        confirmLabel="Delete project"
        onCancel={() => setToDelete(null)}
        onConfirm={() => {
          if (toDelete) {
            remove.mutate(toDelete.id);
            if (toDelete.id === currentProjectId) set({ currentProjectId: null });
          }
          setToDelete(null);
        }}
      />
    </>
  );
}
