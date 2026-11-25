import { describe, expect, it } from "vitest";
import en from "@/i18n/en";
import hi from "@/i18n/hi";
import { GROUPS, MODULES, visibleModules } from "./registry";

describe("module registry", () => {
  it("has unique ids and paths", () => {
    expect(new Set(MODULES.map((m) => m.id)).size).toBe(MODULES.length);
    expect(new Set(MODULES.map((m) => m.path)).size).toBe(MODULES.length);
  });

  it("gives every implemented page a component and every planned page none", () => {
    for (const m of MODULES) {
      if (m.status === "implemented") expect(m.component, m.id).toBeDefined();
      else expect(m.component, m.id).toBeUndefined();
    }
  });

  it("uses known groups and has labels in every language", () => {
    for (const m of MODULES) {
      expect(GROUPS).toContain(m.group);
      expect(en.nav[m.id]).toBeTruthy();
      expect(hi.nav[m.id]).toBeTruthy();
    }
  });

  it("hides pages the user lacks permission for", () => {
    const ids = visibleModules(["plugin:read"]).map((m) => m.id);
    expect(ids).toContain("catalogue");
    expect(ids).not.toContain("users");
  });
});
