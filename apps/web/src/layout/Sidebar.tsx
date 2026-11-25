import { ChevronDown, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";
import { useMe } from "@/api/hooks";
import { cn } from "@/lib/cn";
import { GROUPS, visibleModules } from "@/modules/registry";
import { useUi } from "@/stores/ui";

export function Sidebar() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const collapsed = useUi((s) => s.sidebarCollapsed);
  const set = useUi((s) => s.set);
  const [closedGroups, setClosedGroups] = useState<Set<string>>(new Set());
  const modules = visibleModules(me?.permissions);

  const toggleGroup = (g: string) =>
    setClosedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(g)) next.delete(g);
      else next.add(g);
      return next;
    });

  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col border-r border-line bg-surface-2 transition-[width] duration-200",
        collapsed ? "w-[60px]" : "w-[252px]",
      )}
    >
      <div className={cn("flex h-14 items-center gap-2.5 px-4", collapsed && "justify-center px-0")}>
        <img src="/favicon.svg" alt="" className="size-7" />
        {!collapsed && (
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-[-0.01em]">SmartAgri-Fog</div>
            <div className="text-xs text-ink-3">Research platform</div>
          </div>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-4" aria-label="Main">
        {GROUPS.map((group) => {
          const items = modules.filter((m) => m.group === group);
          if (!items.length) return null;
          const closed = closedGroups.has(group) && !collapsed;
          return (
            <div key={group} className="mt-4 first:mt-1">
              {!collapsed && (
                <button
                  type="button"
                  onClick={() => toggleGroup(group)}
                  className="flex w-full items-center justify-between rounded px-2 py-1 text-xs font-medium text-ink-3 hover:text-ink-2"
                  aria-expanded={!closed}
                >
                  {t(`groups.${group}`)}
                  <ChevronDown className={cn("size-3.5 transition-transform", closed && "-rotate-90")} />
                </button>
              )}
              {!closed && (
                <ul className="mt-1 space-y-px">
                  {items.map((m) => {
                    const Icon = m.icon;
                    const planned = m.status === "planned";
                    const label = t(`nav.${m.id}`);
                    return (
                      <li key={m.id}>
                        <NavLink
                          to={m.path}
                          end={m.path === "/"}
                          title={planned ? `${label}: planned for Phase ${m.phase}` : label}
                          className={({ isActive }) =>
                            cn(
                              "group flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm",
                              collapsed && "justify-center",
                              isActive
                                ? "bg-surface font-medium text-ink shadow-[inset_2px_0_0_var(--accent)]"
                                : planned
                                  ? "text-ink-3 hover:bg-surface/60 hover:text-ink-2"
                                  : "text-ink-2 hover:bg-surface/60 hover:text-ink",
                            )
                          }
                        >
                          <Icon className="size-4 shrink-0" strokeWidth={1.75} />
                          {!collapsed && (
                            <>
                              <span className="truncate">{label}</span>
                              {planned && (
                                <span
                                  className="ml-auto size-1.5 shrink-0 rounded-full border border-current opacity-70"
                                  aria-label="planned"
                                />
                              )}
                            </>
                          )}
                        </NavLink>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </nav>

      <div className={cn("flex items-center border-t border-line p-2", collapsed ? "justify-center" : "justify-between")}>
        {!collapsed && (
          <span className="flex items-center gap-1.5 px-2 text-xs text-ink-3">
            <span className="size-1.5 rounded-full border border-current" /> planned page
          </span>
        )}
        <button
          type="button"
          onClick={() => set({ sidebarCollapsed: !collapsed })}
          className="rounded-md p-1.5 text-ink-3 hover:bg-surface hover:text-ink"
          aria-label={collapsed ? t("shell.expand") : t("shell.collapse")}
        >
          {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
        </button>
      </div>
    </aside>
  );
}
