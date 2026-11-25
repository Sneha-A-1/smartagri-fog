import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { CURRENT_PHASE, PHASES } from "@/lib/roadmap";
import type { ModuleManifest } from "@/modules/registry";

/** Shown for pages that are on the roadmap but not built yet. States plainly what is missing. */
export function PlannedPage({ module }: { module: ModuleManifest }) {
  const { t } = useTranslation();
  const Icon = module.icon;
  const phase = PHASES[module.phase];
  const wait = module.phase - CURRENT_PHASE;

  return (
    <div className="max-w-2xl py-6">
      <Icon className="size-8 text-ink-3" strokeWidth={1.5} />
      <h1 className="mt-4 flex flex-wrap items-center gap-3 text-[1.65rem] font-semibold tracking-[-0.01em]">
        {t(`nav.${module.id}`)} <StatusBadge status="planned" />
      </h1>
      <p className="mt-3 text-ink-2">{module.description}</p>
      <div className="mt-8 border-l-2 border-line pl-4 text-sm">
        <p>
          Built in <span className="font-medium">Phase {module.phase}: {phase?.name}</span>
          {wait > 0 && `, ${wait} ${wait === 1 ? "phase" : "phases"} from now`}.
        </p>
        <p className="mt-1 text-ink-3">{phase?.goal}.</p>
      </div>
      <p className="mt-8 text-sm text-ink-3">
        Nothing on this page works yet, and it shows no data. Meanwhile you can browse the{" "}
        <Link to="/algorithms" className="text-accent hover:underline">
          algorithm catalogue
        </Link>{" "}
        or run the soil-moisture demo.
      </p>
    </div>
  );
}
