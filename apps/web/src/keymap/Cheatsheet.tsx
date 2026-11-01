import { useEffect, useRef, useSyncExternalStore, type CSSProperties } from "react";
import { Link } from "@candleviewer/ui";
import { KEYMAP } from "./keymap";
import { getBindings, subscribeBindings } from "./profile";
import { commandMeta, globalShadowNote } from "./registry";
import { holdsReservedOverride } from "./validate";

const FOCUSABLE = "a[href], button:not([disabled])";

// A fixed sheet over the page in tokens, scrolling inside the viewport (D-03: it rendered below the fold).
const sheet: CSSProperties = {
  position: "fixed",
  inset: "var(--space-6)",
  overflow: "auto",
  padding: "var(--space-6)",
  background: "var(--color-surface-raised)",
  color: "var(--color-text-primary)",
  border: "1px solid var(--color-border-default)",
  borderRadius: "var(--radius-lg)",
  fontFamily: "var(--font-family-ui)",
};

/**
 * SCR-013 overlay: current bindings by context as a real table; conflicts get a warning chip, and a view's declared
 * shadow of a Global key shows its rationale beside the key (BQ-4: no override is silent, `05` §3.1 rule 2). The
 * reserved `Ctrl+K` and `Esc` read "not remappable" (BQ-7; E10-D04 §15), and a binding still on its reviewed override
 * of a browser or OS key reads "reserved by the browser or OS" (E10-D04 §15, DS-305B-02); an unbound command reads
 * "unbound".
 *
 * A modal dialog (CMP-094, CMP-043 composition; D-03 / A11Y-F-0026): focus moves in on open (to Close), Tab cycles
 * inside, Esc calls `onClose`, and on close focus returns to the element that had it.
 */
export function Cheatsheet({ onClose }: { readonly onClose?: () => void }): JSX.Element {
  const b = useSyncExternalStore(subscribeBindings, getBindings);
  const seen = new Map<string, number>();
  for (const c of KEYMAP) {
    if (b.get(c.id) === "") continue; // unbound
    const k = `${c.context}|${b.get(c.id)}`;
    seen.set(k, (seen.get(k) ?? 0) + 1);
  }
  const contexts = [...new Set(KEYMAP.map((c) => c.context))];
  const dialog = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const opener = document.activeElement;
    (closeButton.current ?? dialog.current)?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  // Esc closes and Tab cycles inside, on the native element (the StepUpDialog pattern).
  useEffect(() => {
    const node = dialog.current;
    if (node === null) return undefined;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && close.current) {
        event.preventDefault();
        event.stopPropagation();
        close.current();
        return;
      }
      if (event.key !== "Tab") return;
      const stops = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      const first = stops[0];
      const last = stops[stops.length - 1];
      if (first === undefined || last === undefined) return;
      const at = document.activeElement;
      if (event.shiftKey && (at === first || at === node)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (at === last || at === node)) {
        event.preventDefault();
        first.focus();
      }
    };
    node.addEventListener("keydown", onKeyDown);
    return () => node.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div
      ref={dialog}
      role="dialog"
      aria-modal="true"
      aria-labelledby="cs-h"
      tabIndex={-1}
      style={sheet}
    >
      <h2 id="cs-h">Keyboard shortcuts</h2>
      <Link href="/settings/hotkeys">Customise</Link>
      {onClose ? (
        <button ref={closeButton} type="button" onClick={onClose}>
          Close
        </button>
      ) : null}
      {contexts.map((ctx) => (
        <table key={ctx}>
          <caption>{ctx}</caption>
          <thead>
            <tr>
              <th scope="col">Command</th>
              <th scope="col">Binding</th>
            </tr>
          </thead>
          <tbody>
            {KEYMAP.filter((c) => c.context === ctx).map((c) => {
              const bound = b.get(c.id) ?? c.defaultBinding;
              const conflict = (seen.get(`${ctx}|${bound}`) ?? 0) > 1;
              const shadow = globalShadowNote(c, b);
              const locked = commandMeta(c.id)?.remappable === false;
              return (
                <tr key={c.id}>
                  <th scope="row">{c.label}</th>
                  <td>
                    {bound === "" ? "unbound" : <kbd>{bound}</kbd>}
                    {locked ? <span> not remappable</span> : null}
                    {holdsReservedOverride(c, bound) ? (
                      <span> reserved by the browser or OS</span>
                    ) : null}
                    {shadow === undefined ? null : <span>{` ${shadow}`}</span>}
                    {conflict ? (
                      <span role="img" aria-label="Warning: conflicting binding">
                        {" "}
                        ⚠ Conflict
                      </span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ))}
    </div>
  );
}
