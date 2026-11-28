import { useId } from "react";
import { cn } from "@/lib/cn";

/** The subset of JSON Schema that Pydantic emits for plugin parameters. */
export type JsonSchemaProperty = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  enum?: unknown[];
  items?: { enum?: unknown[]; type?: string };
  minItems?: number;
  "x-unit"?: string;
  "x-advanced"?: boolean;
};

export type JsonSchema = { properties?: Record<string, JsonSchemaProperty>; required?: string[] };

export type FieldErrors = Record<string, string>;

/**
 * Builds a parameter form from a plugin's JSON Schema, so new algorithms need no form code.
 * Fields marked `x-advanced` appear only in researcher mode.
 */
export function SchemaForm({
  schema,
  values,
  onChange,
  errors = {},
  showAdvanced,
  disabled,
}: {
  schema: JsonSchema;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  errors?: FieldErrors;
  showAdvanced: boolean;
  disabled?: boolean;
}) {
  const entries = Object.entries(schema.properties ?? {});
  const visible = entries.filter(([, p]) => showAdvanced || !p["x-advanced"]);
  const hiddenCount = entries.length - visible.length;

  return (
    <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2">
      {visible.map(([name, prop]) => (
        <Field
          key={name}
          name={name}
          prop={prop}
          value={values[name]}
          error={errors[name]}
          disabled={disabled}
          onChange={(v) => onChange({ ...values, [name]: v })}
        />
      ))}
      {hiddenCount > 0 && (
        <p className="text-sm text-ink-3 sm:col-span-2">
          {hiddenCount} advanced {hiddenCount === 1 ? "setting is" : "settings are"} hidden. Switch to researcher mode
          in the top bar to see {hiddenCount === 1 ? "it" : "them"}.
        </p>
      )}
    </div>
  );
}

function Field({
  name,
  prop,
  value,
  error,
  disabled,
  onChange,
}: {
  name: string;
  prop: JsonSchemaProperty;
  value: unknown;
  error?: string;
  disabled?: boolean;
  onChange: (v: unknown) => void;
}) {
  const id = useId();
  const label = sentenceCase(prop.title ?? name);
  const unit = prop["x-unit"];
  const min = prop.minimum ?? prop.exclusiveMinimum;
  const max = prop.maximum ?? prop.exclusiveMaximum;
  const u = unit ? ` ${unit}` : "";
  const range =
    min !== undefined && max !== undefined
      ? `Range ${min} to ${max}${u}.`
      : min !== undefined
        ? `At least ${min}${u}.`
        : max !== undefined
          ? `At most ${max}${u}.`
          : null;
  const help = [prop.description, range].filter(Boolean).join(" ");

  const inputClass = cn(
    "w-full rounded-lg border bg-surface px-3 py-2 text-sm tabular-nums",
    error ? "border-danger" : "border-line",
  );

  let control;
  if (prop.type === "array" && prop.items?.enum) {
    const selected = new Set(Array.isArray(value) ? (value as unknown[]).map(String) : []);
    control = (
      <div id={id} role="group" aria-describedby={`${id}-help`} className="flex flex-wrap gap-1.5">
        {prop.items.enum.map((opt) => {
          const key = String(opt);
          const on = selected.has(key);
          return (
            <button
              key={key}
              type="button"
              aria-pressed={on}
              disabled={disabled}
              onClick={() => {
                const next = (prop.items!.enum as unknown[]).map(String).filter((o) => (o === key ? !on : selected.has(o)));
                onChange(next);
              }}
              className={cn(
                "rounded-md border px-2.5 py-1 text-sm",
                on ? "border-accent bg-accent-soft text-accent" : "border-line bg-surface text-ink-2 hover:bg-surface-2",
              )}
            >
              {optionLabel(key)}
            </button>
          );
        })}
      </div>
    );
  } else if (prop.type === "boolean") {
    control = (
      <input
        id={id}
        type="checkbox"
        className="size-4 accent-[var(--accent)]"
        checked={Boolean(value)}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  } else if (prop.enum) {
    control = (
      <select
        id={id}
        className={inputClass}
        value={String(value ?? "")}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {prop.enum.map((opt) => (
          <option key={String(opt)} value={String(opt)}>
            {optionLabel(String(opt))}
          </option>
        ))}
      </select>
    );
  } else if (prop.type === "integer" || prop.type === "number") {
    control = (
      <input
        id={id}
        type="number"
        inputMode="decimal"
        className={inputClass}
        value={value === undefined || value === null ? "" : String(value)}
        min={min}
        max={max}
        step={prop.type === "integer" ? 1 : "any"}
        disabled={disabled}
        aria-invalid={Boolean(error)}
        aria-describedby={`${id}-help`}
        onChange={(e) => {
          const raw = e.target.value;
          onChange(raw === "" ? undefined : prop.type === "integer" ? Number.parseInt(raw, 10) : Number(raw));
        }}
      />
    );
  } else {
    control = (
      <input
        id={id}
        className={inputClass}
        value={String(value ?? "")}
        disabled={disabled}
        aria-invalid={Boolean(error)}
        aria-describedby={`${id}-help`}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  return (
    <div className={cn(prop.type === "boolean" && "flex items-start gap-3")}>
      <label htmlFor={id} className="mb-1.5 flex items-baseline justify-between gap-2 text-sm font-medium">
        <span>
          {label}
          {prop["x-advanced"] && <span className="ml-2 text-xs font-normal text-ink-3">advanced</span>}
        </span>
        {unit && <span className="text-xs font-normal text-ink-3">{unit}</span>}
      </label>
      {control}
      {error ? (
        <p className="mt-1 text-xs text-danger">{error}</p>
      ) : (
        help && (
          <p id={`${id}-help`} className="mt-1 text-xs text-ink-3">
            {help}
          </p>
        )
      )}
    </div>
  );
}

/** "Samples Per Day" -> "Samples per day"; keeps acronyms such as "CPU" or "NDVI". */
function sentenceCase(title: string): string {
  return title
    .replace(/_/g, " ")
    .split(" ")
    .map((w, i) => (i === 0 || /^[A-Z0-9]{2,}$/.test(w) ? w : w.toLowerCase()))
    .join(" ");
}

/** Readable labels for enum values used by scheduling parameters. Unknown values are shown as-is. */
const OPTION_LABELS: Record<string, string> = {
  random: "Random",
  round_robin: "Round Robin",
  least_loaded: "Least Loaded",
  mct: "Minimum Completion Time",
  cloud_only: "Cloud-only",
  edge_ward: "Edge-ward",
  min_min: "Min-Min",
  max_min: "Max-Min",
  fcfs: "First-Come, First-Served",
  edf: "Earliest Deadline First",
  priority: "Priority",
  sjf: "Shortest Job First",
  ga: "Genetic Algorithm (batch)",
  pso: "Particle Swarm (batch)",
  aco: "Ant Colony (batch)",
  gwo: "Grey Wolf (batch)",
  woa: "Whale Optimization (batch)",
  nsga2: "NSGA-II (batch)",
  random_search: "Random search (batch)",
  dqn: "Deep Q-Network (learned)",
  aura: "AURA (proposed)",
  aura_noaoi: "AURA without AoI",
  aura_noreserve: "AURA without reservation",
  aura_staticreserve: "AURA with static reservation",
  aura_noreliability: "AURA without reliability",
  aura_singletier: "AURA single tier",
  urgent_edf: "Urgent first, earliest deadline",
  none: "Original workload",
  normal: "Normal load with data freshness",
  monsoon_burst: "Monsoon burst",
  heat_wave: "Heat wave",
  cloud_disconnection: "Cloud disconnection",
  fog_failure: "Fog server failure",
};

export function optionLabel(value: string): string {
  return OPTION_LABELS[value] ?? value;
}
