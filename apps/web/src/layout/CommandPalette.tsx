import { Command } from "cmdk";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useMe, usePlugins } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { visibleModules } from "@/modules/registry";
import { useUi } from "@/stores/ui";

/** Ctrl+K: jump to any page or algorithm. */
export function CommandPalette() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const open = useUi((s) => s.paletteOpen);
  const set = useUi((s) => s.set);
  const { data: me } = useMe();
  const { data: plugins } = usePlugins();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        set({ paletteOpen: !useUi.getState().paletteOpen });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [set]);

  const go = (path: string) => {
    set({ paletteOpen: false });
    navigate(path);
  };

  const itemClass =
    "flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm data-[selected=true]:bg-accent-soft";

  return (
    <Command.Dialog
      open={open}
      onOpenChange={(o) => set({ paletteOpen: o })}
      label="Search"
      overlayClassName="fixed inset-0 z-40 bg-black/30"
      contentClassName="fixed left-1/2 top-[12vh] z-50 w-[min(36rem,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-xl border border-line bg-surface text-ink shadow-2xl"
    >
      <Command.Input
        placeholder={t("shell.search")}
        className="w-full border-b border-line bg-transparent px-4 py-3 text-sm outline-none"
      />
      <Command.List className="max-h-[55vh] overflow-y-auto p-2">
        <Command.Empty className="px-3 py-6 text-center text-sm text-ink-3">Nothing matches that search.</Command.Empty>
        <Command.Group heading="Pages" className="text-xs text-ink-3 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5">
          {visibleModules(me?.permissions).map((m) => {
            const Icon = m.icon;
            return (
              <Command.Item
                key={m.id}
                value={`${t(`nav.${m.id}`)} ${m.description}`}
                onSelect={() => go(m.path)}
                className={itemClass}
              >
                <Icon className="size-4 text-ink-3" strokeWidth={1.75} />
                <span className="text-ink">{t(`nav.${m.id}`)}</span>
                {m.status === "planned" && <span className="ml-auto text-xs text-ink-3">Phase {m.phase}</span>}
              </Command.Item>
            );
          })}
        </Command.Group>
        <Command.Group heading="Algorithms" className="text-xs text-ink-3 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5">
          {plugins?.map((p) => (
            <Command.Item
              key={p.id}
              value={`${p.name} ${p.kind} ${p.summary}`}
              onSelect={() => go(`/algorithms/${encodeURIComponent(p.id)}`)}
              className={itemClass}
            >
              <span className="truncate text-ink">{p.name}</span>
              <StatusBadge status={p.status} className="ml-auto" />
            </Command.Item>
          ))}
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
