// E17-T05: renders the 23-ws-protocol.md 10.3 treatments for err frames:
// fatal -> blocking modal, transient -> staleness badge, client bug / capacity -> toast.
import { useEffect, useRef, useState } from "react";
import { Button, Dialog } from "@candleviewer/ui";
import { onWsError } from "./errorHandler";
import type { ErrorTreatment } from "./errorMapping";

interface Surface {
  readonly modal: string | null;
  readonly badge: string | null;
  readonly toast: { readonly code: string; readonly kind: "reportBug" | "fewerPanes" } | null;
}

const EMPTY: Surface = { modal: null, badge: null, toast: null };

export function reduceSurface(s: Surface, code: string, t: ErrorTreatment): Surface {
  return {
    modal: t.modal ? code : s.modal,
    badge: t.inlineBadge ? code : s.badge,
    toast: t.toast === "none" ? s.toast : { code, kind: t.toast },
  };
}

export function WsErrorHost(): JSX.Element | null {
  const [s, setS] = useState<Surface>(EMPTY);
  const dismiss = useRef<HTMLSpanElement>(null);
  useEffect(() => onWsError((code, t) => setS((prev) => reduceSurface(prev, code, t))), []);
  if (!s.modal && !s.badge && !s.toast) return null;
  return (
    <>
      {s.modal ? (
        <Dialog
          open
          role="alertdialog"
          title="Connection error"
          description={`Session error (${s.modal}). Sign in again or contact an owner.`}
          initialFocusRef={dismiss}
          onOpenChange={() => setS((p) => ({ ...p, modal: null }))}
          footer={
            <span ref={dismiss}>
              <Button variant="primary" onClick={() => setS((p) => ({ ...p, modal: null }))}>
                Dismiss
              </Button>
            </span>
          }
        />
      ) : null}
      {s.badge ? (
        <div role="status" aria-live="polite">
          Data may be stale ({s.badge})
        </div>
      ) : null}
      {s.toast ? (
        <div role="status" aria-live="polite">
          {s.toast.kind === "reportBug"
            ? `Unexpected client error (${s.toast.code}). Please report a bug.`
            : `Server capacity reached (${s.toast.code}). Try fewer panes.`}
        </div>
      ) : null}
    </>
  );
}
