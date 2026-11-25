import { useEffect, useRef } from "react";
import { useSaveServerSettings, useServerSettings } from "@/api/hooks";
import { type Mode, type Theme, useUi } from "@/stores/ui";

/** Loads theme, language and mode from your server profile once, then saves changes back (debounced). */
export function useSettingsSync(): void {
  const { data } = useServerSettings();
  const save = useSaveServerSettings();
  const loaded = useRef(false);
  const theme = useUi((s) => s.theme);
  const language = useUi((s) => s.language);
  const mode = useUi((s) => s.mode);
  const set = useUi((s) => s.set);

  useEffect(() => {
    if (!data || loaded.current) return;
    loaded.current = true;
    const v = data.values as { theme?: Theme; language?: string; mode?: Mode };
    if (v.theme || v.language || v.mode) set({ ...v });
  }, [data, set]);

  const { mutate } = save;
  useEffect(() => {
    if (!loaded.current) return;
    const timer = setTimeout(() => mutate({ ...(data?.values ?? {}), theme, language, mode }), 600);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, language, mode, mutate]);
}
