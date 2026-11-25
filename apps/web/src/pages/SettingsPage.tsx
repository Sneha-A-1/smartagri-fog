import { useSaveServerSettings, useSystemInfo } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { LANGUAGES } from "@/i18n";
import { cn } from "@/lib/cn";
import { type Mode, type Theme, useUi } from "@/stores/ui";

export default function SettingsPage() {
  const ui = useUi();
  const { data: info } = useSystemInfo();
  const save = useSaveServerSettings();

  return (
    <>
      <PageHeader
        title="Settings"
        lead="Your preferences are saved to your profile on this computer and apply every time you open the platform."
      />

      <div className="max-w-2xl space-y-10">
        <Choice<Theme>
          label="Theme"
          value={ui.theme}
          options={[
            ["system", "Match my computer"],
            ["light", "Light"],
            ["dark", "Dark"],
          ]}
          onChange={(theme) => ui.set({ theme })}
        />
        <Choice<string>
          label="Language"
          help="Navigation and interface labels. Page content is translated as each page is finished."
          value={ui.language}
          options={LANGUAGES.map((l) => [l.code, l.label])}
          onChange={(language) => ui.set({ language })}
        />
        <Choice<Mode>
          label="Interface mode"
          help="Beginner mode shows the essential parameters with sensible defaults. Researcher mode shows every parameter."
          value={ui.mode}
          options={[
            ["beginner", "Beginner"],
            ["researcher", "Researcher"],
          ]}
          onChange={(mode) => ui.set({ mode })}
        />
        <p className="text-sm text-ink-3" aria-live="polite">
          {save.isPending ? "Saving…" : save.isError ? `Couldn't save: ${save.error.message}` : save.isSuccess ? "Saved to your profile." : ""}
        </p>

        <section>
          <h2 className="text-lg font-semibold">System</h2>
          <dl className="mt-3 divide-y divide-line border-y border-line text-sm">
            {info &&
              (
                [
                  ["Platform version", `API ${info.version}, core ${info.core_version}, Python ${info.python}`],
                  ["Mode", info.local_mode ? "Local mode: single user, no sign-in" : "Multi-user, sign-in required"],
                  ["Data folder", info.data_dir],
                  ["Results folder", info.results_dir],
                  ["Parallel job workers", String(info.job_workers)],
                ] as const
              ).map(([k, v]) => (
                <div key={k} className="grid grid-cols-[11rem_1fr] gap-3 py-2">
                  <dt className="text-ink-3">{k}</dt>
                  <dd className="break-all">{v}</dd>
                </div>
              ))}
          </dl>
          <p className="mt-3 text-sm text-ink-3">
            Folders and workers are set in the <code>.env</code> file at the project root (for example{" "}
            <code>SMARTAGRI_RESULTS_DIR=E:\SmartAgriData\results</code>). Restart the platform after changing it.
          </p>
          {info && info.plugin_load_errors.length > 0 && (
            <div className="mt-4 rounded-lg border border-danger p-3 text-sm text-danger">
              <p className="font-medium">Plugin packages that failed to load</p>
              <ul className="mt-1 list-disc pl-5">
                {info.plugin_load_errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </div>
    </>
  );
}

function Choice<T extends string>({
  label,
  help,
  value,
  options,
  onChange,
}: {
  label: string;
  help?: string;
  value: T;
  options: readonly (readonly [T, string])[];
  onChange: (v: T) => void;
}) {
  return (
    <fieldset>
      <legend className="text-sm font-medium">{label}</legend>
      {help && <p className="mt-0.5 text-sm text-ink-3">{help}</p>}
      <div className="mt-2 flex flex-wrap gap-2">
        {options.map(([v, text]) => (
          <button
            key={v}
            type="button"
            aria-pressed={value === v}
            onClick={() => onChange(v)}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-sm",
              value === v ? "border-accent bg-accent-soft font-medium text-accent" : "border-line bg-surface hover:bg-surface-2",
            )}
          >
            {text}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
