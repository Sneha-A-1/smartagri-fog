import { useEffect, useRef } from "react";
import { Button } from "./Button";

/** Asks before an action that cannot be undone. Uses the native <dialog> for focus trapping and Esc. */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal?.();
    if (!open && el.open) el.close?.();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onCancel}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-xl border border-line bg-surface p-0 text-ink shadow-xl backdrop:bg-black/40"
    >
      <div className="p-5">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-2 text-sm text-ink-2">{body}</p>
      </div>
      <div className="flex justify-end gap-2 border-t border-line px-5 py-3">
        <Button onClick={onCancel}>Keep it</Button>
        <Button variant="danger" onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
