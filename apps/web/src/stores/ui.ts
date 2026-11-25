import { create } from "zustand";

export type Theme = "light" | "dark" | "system";
export type Mode = "beginner" | "researcher";

type UiState = {
  theme: Theme;
  language: string;
  mode: Mode;
  sidebarCollapsed: boolean;
  currentProjectId: string | null;
  paletteOpen: boolean;
  set: (patch: Partial<Omit<UiState, "set">>) => void;
};

const KEY = "smartagri.ui";
const PERSISTED: (keyof UiState)[] = ["theme", "language", "mode", "sidebarCollapsed", "currentProjectId"];

function load(): Partial<UiState> {
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? "{}");
  } catch {
    return {};
  }
}

/** Per-viewer interface preferences. Saved in the browser; theme, language and mode also sync to the server. */
export const useUi = create<UiState>((set, get) => ({
  theme: "system",
  language: "en",
  mode: "beginner",
  sidebarCollapsed: false,
  currentProjectId: null,
  paletteOpen: false,
  ...load(),
  set: (patch) => {
    set(patch);
    try {
      const state = get();
      const keep = Object.fromEntries(PERSISTED.map((k) => [k, state[k]]));
      window.localStorage.setItem(KEY, JSON.stringify(keep));
    } catch {
      /* storage unavailable: preferences last for this session only */
    }
  },
}));

export function applyTheme(theme: Theme): void {
  const dark =
    theme === "dark" || (theme === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", Boolean(dark));
}
