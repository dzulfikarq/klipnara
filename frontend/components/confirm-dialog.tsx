"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

type ConfirmOptions = { title?: string; confirmLabel?: string; cancelLabel?: string; destructive?: boolean };
type PendingConfirm = Required<ConfirmOptions> & { message: string };
type Confirm = (message: string, options?: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const resolver = useRef<((confirmed: boolean) => void) | null>(null);
  const [pending, setPending] = useState<PendingConfirm | null>(null);

  const finish = useCallback((confirmed: boolean) => {
    const resolve = resolver.current;
    if (!resolve) return;
    resolver.current = null;
    setPending(null);
    if (dialog.current?.open) dialog.current.close();
    resolve(confirmed);
  }, []);

  const confirm = useCallback<Confirm>((message, options = {}) => new Promise((resolve) => {
    resolver.current?.(false);
    resolver.current = resolve;
    setPending({
      message,
      title: options.title ?? "Konfirmasi tindakan",
      confirmLabel: options.confirmLabel ?? "Lanjutkan",
      cancelLabel: options.cancelLabel ?? "Batal",
      destructive: options.destructive ?? false,
    });
  }), []);

  useEffect(() => {
    if (pending && dialog.current && !dialog.current.open) dialog.current.showModal();
  }, [pending]);

  return <ConfirmContext.Provider value={confirm}>
    {children}
    <dialog ref={dialog} className="confirm-dialog" aria-labelledby="confirm-dialog-title" aria-describedby="confirm-dialog-message"
      onCancel={(event) => { event.preventDefault(); finish(false); }}
      onClick={(event) => { if (event.target === dialog.current) finish(false); }}>
      {pending && <>
        <h2 id="confirm-dialog-title">{pending.title}</h2>
        <p id="confirm-dialog-message">{pending.message}</p>
        <div className="confirm-dialog-actions">
          <button type="button" className="button button-outline" onClick={() => finish(false)}>{pending.cancelLabel}</button>
          <button type="button" className={`button ${pending.destructive ? "button-danger" : "button-primary"}`} onClick={() => finish(true)}>{pending.confirmLabel}</button>
        </div>
      </>}
    </dialog>
  </ConfirmContext.Provider>;
}

export function useConfirm() {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error("useConfirm must be used inside ConfirmProvider");
  return confirm;
}
