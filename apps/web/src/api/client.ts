import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

/** Typed API client generated from the backend's OpenAPI schema (run `npm run gen:api` after API changes). */
export const api = createClient<paths>({ baseUrl: "" });

let token: string | null = null;
try {
  token = window.localStorage.getItem("smartagri.token");
} catch {
  token = null;
}

api.use({
  onRequest({ request }) {
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
});

export function setToken(value: string | null): void {
  token = value;
  try {
    if (value) window.localStorage.setItem("smartagri.token", value);
    else window.localStorage.removeItem("smartagri.token");
  } catch {
    /* storage unavailable: token lives in memory only */
  }
}

export type Plugin = components["schemas"]["PluginSummary"];
export type PluginDetail = components["schemas"]["PluginDetail"];
export type Job = components["schemas"]["JobOut"];
export type Project = components["schemas"]["ProjectOut"];
export type User = components["schemas"]["UserOut"];
export type SystemInfo = components["schemas"]["SystemInfo"];
export type Experiment = components["schemas"]["ExperimentOut"];
export type ExperimentSchema = components["schemas"]["ExperimentSchemaOut"];
export type LitEntry = components["schemas"]["EntryOut"];
export type Farm = components["schemas"]["FarmOut"];
export type FarmFieldT = components["schemas"]["FieldOut"];
export type WaterBalance = components["schemas"]["WaterBalanceOut"];
export type WeatherData = components["schemas"]["WeatherOut"];
export type AgroPresets = components["schemas"]["AgroPresets"];
export type DeviceT = components["schemas"]["DeviceOut"];
export type Twin = components["schemas"]["TwinOut"];
export type RetrievalRun = components["schemas"]["RunOut"];
export type DatasetT = components["schemas"]["DatasetOut"];

/** Turns an API error body into one readable sentence. */
export function errorMessage(error: unknown): string {
  if (!error) return "Unknown error";
  if (typeof error === "string") return error;
  const detail = (error as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join(".")}: ${d.msg}`).join("; ");
  return JSON.stringify(error);
}
