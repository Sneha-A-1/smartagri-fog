import { useState } from "react";
import { Link } from "react-router-dom";
import { useDeleteTopology, useDuplicateTopology, useTopologies } from "@/api/hooks";
import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { formatTime } from "@/lib/format";

export default function Topologies() {
  const { data: topologies, isLoading } = useTopologies();
  const duplicate = useDuplicateTopology();
  const del = useDeleteTopology();
  const [toDelete, setToDelete] = useState<{ id: string; name: string } | null>(null);

  return (
    <>
      <PageHeader
        title="Topology designer"
        lead="Design the IoT, edge, fog and cloud network that simulations run on: draw it node by node, or generate a farm network and adjust it."
        actions={
          <Link to="/topology/new" className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-accent-ink hover:bg-accent-hover">
            New topology
          </Link>
        }
      />
      {isLoading && <p className="text-sm text-ink-3">Loading…</p>}
      {topologies?.length === 0 && <p className="text-sm text-ink-2">No saved topologies yet. Create one to design your own farm network.</p>}
      <ul className="divide-y divide-line border-y border-line">
        {topologies?.map((t) => (
          <li key={t.id} className="flex flex-wrap items-center gap-4 py-3.5">
            <Link to={`/topology/${t.id}`} className="min-w-0 flex-1 hover:text-accent">
              <div className="font-medium">{t.name}</div>
              <p className="mt-0.5 text-xs text-ink-3">
                {t.nodes} nodes, {t.links} links. Updated {formatTime(t.updated_at)}.
              </p>
            </Link>
            <Button variant="ghost" onClick={() => duplicate.mutate(t.id)}>Duplicate</Button>
            <Button variant="ghost" onClick={() => setToDelete({ id: t.id, name: t.name })}>Delete</Button>
          </li>
        ))}
      </ul>
      <ConfirmDialog open={toDelete !== null} title={`Delete "${toDelete?.name}"?`}
        body="The saved topology is removed. Experiments that used it keep their own copy, so their results stay reproducible."
        confirmLabel="Delete topology" onCancel={() => setToDelete(null)}
        onConfirm={() => { if (toDelete) del.mutate(toDelete.id); setToDelete(null); }} />
    </>
  );
}
