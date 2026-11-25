import type { ReactNode } from "react";

export function PageHeader({ title, lead, actions }: { title: string; lead?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="text-[1.65rem] leading-tight font-semibold tracking-[-0.01em]">{title}</h1>
        {lead && <p className="mt-2 text-ink-2">{lead}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}
