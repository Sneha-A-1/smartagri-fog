import { useTranslation } from "react-i18next";
import { cn } from "@/lib/cn";

const STYLES: Record<string, string> = {
  implemented: "text-[var(--st-implemented)] bg-[var(--st-implemented-bg)]",
  simulated: "text-[var(--st-simulated)] bg-[var(--st-simulated-bg)]",
  "needs-integration": "text-[var(--st-integration)] bg-[var(--st-integration-bg)]",
  planned: "text-[var(--st-planned)] bg-[var(--st-planned-bg)]",
};

const DOT: Record<string, string> = {
  implemented: "bg-[var(--st-implemented)]",
  simulated: "bg-[var(--st-simulated)]",
  "needs-integration": "bg-[var(--st-integration)]",
  planned: "border border-[var(--st-planned)]",
};

/** Capability status. The dot's fill encodes status even without colour: hollow = planned. */
export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const { t } = useTranslation();
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        STYLES[status] ?? STYLES.planned,
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", DOT[status] ?? DOT.planned)} aria-hidden />
      {t(`status.${status}`, { defaultValue: status })}
    </span>
  );
}

/** Data provenance. Shown on every chart, table and result built on data. */
export function OriginBadge({ origin }: { origin: string | null | undefined }) {
  const { t } = useTranslation();
  if (!origin) return null;
  const real = origin === "real";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium",
        real
          ? "border-[var(--st-implemented)] text-[var(--st-implemented)]"
          : "border-dashed border-[var(--st-simulated)] text-[var(--st-simulated)]",
      )}
    >
      {t(`origin.${origin}`, { defaultValue: origin })}
    </span>
  );
}
