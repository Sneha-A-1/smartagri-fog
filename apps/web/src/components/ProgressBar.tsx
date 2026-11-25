import { cn } from "@/lib/cn";

export function ProgressBar({ value, status, className }: { value: number; status: string; className?: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const tone =
    status === "failed" || status === "interrupted"
      ? "bg-danger"
      : status === "cancelled"
        ? "bg-ink-3"
        : status === "succeeded"
          ? "bg-[var(--st-implemented)]"
          : "bg-accent";
  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-2", className)}
    >
      <div className={cn("h-full rounded-full transition-[width] duration-300", tone)} style={{ width: `${pct}%` }} />
    </div>
  );
}
