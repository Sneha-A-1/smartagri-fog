import { Suspense, useEffect } from "react";
import { Outlet } from "react-router-dom";
import { useJobEvents } from "@/api/useJobEvents";
import i18n from "@/i18n";
import { applyTheme, useUi } from "@/stores/ui";
import { CommandPalette } from "./CommandPalette";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useSettingsSync } from "./useSettingsSync";

export function AppShell() {
  const theme = useUi((s) => s.theme);
  const language = useUi((s) => s.language);
  useJobEvents();
  useSettingsSync();

  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system") return;
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq?.addEventListener("change", onChange);
    return () => mq?.removeEventListener("change", onChange);
  }, [theme]);

  useEffect(() => {
    void i18n.changeLanguage(language);
    document.documentElement.lang = language;
  }, [language]);

  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl px-6 py-8 lg:px-10">
            <Suspense fallback={<p className="text-sm text-ink-3">Loading…</p>}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>
      <CommandPalette />
    </div>
  );
}
