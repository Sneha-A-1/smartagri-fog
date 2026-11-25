import { Activity, Monitor, Moon, Search, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router-dom";
import { useHealth, useJobs, useProjects } from "@/api/hooks";
import { LANGUAGES } from "@/i18n";
import { cn } from "@/lib/cn";
import { MODULES } from "@/modules/registry";
import { type Theme, useUi } from "@/stores/ui";

const NEXT_THEME: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
const THEME_ICON = { system: Monitor, light: Sun, dark: Moon };

export function TopBar() {
  const { t } = useTranslation();
  const location = useLocation();
  const ui = useUi();
  const { data: health, isError } = useHealth();
  const { data: jobs } = useJobs();
  const { data: projects } = useProjects();

  const current =
    MODULES.filter((m) => (m.path === "/" ? location.pathname === "/" : location.pathname.startsWith(m.path)))
      .sort((a, b) => b.path.length - a.path.length)[0] ?? MODULES[0];
  const running = jobs?.filter((j) => j.status === "running" || j.status === "queued").length ?? 0;
  const ThemeIcon = THEME_ICON[ui.theme];

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
      <nav aria-label="Breadcrumb" className="hidden shrink-0 items-center gap-1.5 text-sm whitespace-nowrap md:flex">
        <span className="text-ink-3">{t(`groups.${current.group}`)}</span>
        <span className="text-ink-3">/</span>
        <span className="truncate font-medium">{t(`nav.${current.id}`)}</span>
      </nav>

      <button
        type="button"
        onClick={() => ui.set({ paletteOpen: true })}
        className="ml-auto flex min-w-0 flex-1 max-w-xs items-center gap-2 rounded-lg border border-line bg-bg px-3 py-1.5 text-sm text-ink-3 hover:text-ink-2 md:ml-6"
      >
        <Search className="size-4" />
        <span className="truncate">{t("shell.search")}</span>
        <kbd className="ml-auto shrink-0 rounded border border-line px-1.5 text-[11px] whitespace-nowrap">Ctrl K</kbd>
      </button>

      <select
        aria-label="Current project"
        className="hidden max-w-44 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm lg:block"
        value={ui.currentProjectId ?? ""}
        onChange={(e) => ui.set({ currentProjectId: e.target.value || null })}
      >
        <option value="">{t("shell.allProjects")}</option>
        {projects?.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>

      <div className="hidden rounded-lg border border-line p-0.5 text-xs sm:flex" role="group" aria-label="Interface mode">
        {(["beginner", "researcher"] as const).map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={ui.mode === m}
            onClick={() => ui.set({ mode: m })}
            className={cn(
              "rounded-md px-2.5 py-1",
              ui.mode === m ? "bg-accent-soft font-medium text-accent" : "text-ink-3 hover:text-ink",
            )}
          >
            {t(`shell.${m}`)}
          </button>
        ))}
      </div>

      <Link
        to="/jobs"
        className={cn(
          "flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm",
          running ? "text-accent" : "text-ink-3 hover:text-ink",
        )}
        title="Jobs"
      >
        <Activity className={cn("size-4", running > 0 && "animate-pulse")} />
        {running > 0 && <span className="tabular-nums">{t("shell.runningJobs", { count: running })}</span>}
      </Link>

      <select
        aria-label="Language"
        className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm"
        value={ui.language}
        onChange={(e) => ui.set({ language: e.target.value })}
      >
        {LANGUAGES.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>

      <button
        type="button"
        onClick={() => ui.set({ theme: NEXT_THEME[ui.theme] })}
        className="rounded-lg p-2 text-ink-2 hover:bg-surface-2"
        aria-label={`Theme: ${ui.theme}`}
        title={`Theme: ${ui.theme}`}
      >
        <ThemeIcon className="size-4" />
      </button>

      <span
        className={cn(
          "hidden shrink-0 rounded-full px-2.5 py-1 text-xs whitespace-nowrap xl:inline",
          isError ? "bg-danger-bg text-danger" : "bg-surface-2 text-ink-3",
        )}
      >
        {isError ? t("shell.apiOffline") : health?.local_mode ? t("shell.localMode") : "Signed in"}
      </span>
    </header>
  );
}
