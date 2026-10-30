import { useEffect, useState, useSyncExternalStore } from "react";
import { createDispatcher } from "./dispatcher";
import { getBindings, subscribeBindings } from "./profile";
import type { KeymapCommand } from "./keymap";
import { Cheatsheet } from "./Cheatsheet";
import { flushAuditOutbox, recordAudit } from "./audit";

/** Command handlers registered by views; a command with no handler / failing predicate is inert. */
const handlers = new Map<string, { run: (digit?: number) => void; isValid: () => boolean }>();
/** `run` gets the pressed digit of a range binding (`Alt+1..9` → 1..9); other bindings pass none. */
export function registerCommand(
  id: string,
  run: (digit?: number) => void,
  isValid: () => boolean = () => true,
) {
  handlers.set(id, { run, isValid });
  return () => void handlers.delete(id);
}

/** Active contexts come from `data-keymap-context` on the focused element's ancestors. */
export function activeContexts(el: Element | null = document.activeElement): Set<string> {
  const s = new Set<string>(["Global"]);
  for (let n = el; n; n = n.parentElement) {
    const c = n.getAttribute("data-keymap-context");
    if (c) s.add(c);
  }
  return s;
}

/** SCR-015 toast host: polite, non-modal, never steals focus. */
export function ToastHost({ messages }: { readonly messages: readonly string[] }): JSX.Element {
  return (
    <div role="status" aria-live="polite" data-testid="toast-host" data-cv-inert-exempt="">
      {messages.map((m, i) => (
        <p key={`${i}-${m}`}>{m}</p>
      ))}
    </div>
  );
}

export function KeymapHost(): JSX.Element {
  const [toasts, setToasts] = useState<readonly string[]>([]);
  const [sheetOpen, setSheetOpen] = useState(false);
  const bindings = useSyncExternalStore(subscribeBindings, getBindings);
  // Real command: the "?" cheatsheet (SCR-013). Other commands register from their owning views.
  useEffect(() => registerCommand("global.cheatsheet", () => setSheetOpen((o) => !o)), []);
  useEffect(() => {
    const on = (e: Event) => recordAudit((e as CustomEvent).detail);
    const retry = () => void flushAuditOutbox();
    window.addEventListener("cv:audit", on);
    window.addEventListener("online", retry);
    retry(); // records left by a failed POST or a reload are re-sent on mount
    return () => {
      window.removeEventListener("cv:audit", on);
      window.removeEventListener("online", retry);
    };
  }, []);
  useEffect(() => {
    const dispatch = createDispatcher({
      bindings,
      now: () => Date.now(),
      isValid: (c: KeymapCommand) => handlers.get(c.id)?.isValid() ?? false,
      execute: (c: KeymapCommand, digit?: number) => handlers.get(c.id)?.run(digit),
      notify: (m) => {
        setToasts((t) => [...t, m]);
        window.setTimeout(() => setToasts((t) => t.slice(1)), 5000);
      },
    });
    const onKey = (e: KeyboardEvent) => {
      // SCR-005 (#1640): nothing that changes state runs behind the idle lock; no command lists "Locked"
      if (document.querySelector('[data-keymap-context="Locked"]') !== null) return;
      const r = dispatch(e, activeContexts());
      if (r.status === "executed") e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [bindings]);
  return (
    <>
      <ToastHost messages={toasts} />
      {sheetOpen ? <Cheatsheet onClose={() => setSheetOpen(false)} /> : null}
    </>
  );
}
