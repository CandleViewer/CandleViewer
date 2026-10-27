import { KEYMAP, eventBinding, rangeDigit, type KeyEventLike, type KeymapCommand } from "./keymap";

export const INERT_NOTICE_WINDOW_MS = 5000;

export type DispatchResult =
  | { readonly status: "executed"; readonly commandId: string }
  | { readonly status: "inert"; readonly commandId: string; readonly notified: boolean }
  | { readonly status: "unbound" };

export interface DispatcherDeps {
  /** Is the command's `validWhen` satisfied in the current focus/context? */
  readonly isValid: (cmd: KeymapCommand) => boolean;
  /** `digit` is the pressed digit of a range binding (`Alt+1..9`), else undefined. */
  readonly execute: (cmd: KeymapCommand, digit?: number) => void;
  /** Non-modal polite notice (toast host, role="status"); must not steal focus. */
  readonly notify: (message: string) => void;
  readonly now: () => number;
  /** Counter of inert presses by command id (observability). */
  readonly countInert?: (commandId: string) => void;
  /** Current bindings (profile); defaults to the keymap defaults. */
  readonly bindings?: ReadonlyMap<string, string>;
}

/** Contextual explanation: what the command needs and where its visible control lives. */
export function inertMessage(c: KeymapCommand): string {
  const where = typeof c.visibleControl === "string" ? ` Use ${c.visibleControl} instead.` : "";
  const ctx = c.context === "Global" ? "" : ` (${c.context} view)`;
  return `${c.label} is not available here${ctx}: it needs ${c.validWhen}.${where}`;
}

/** Resolve binding -> command -> validWhen -> execute, or explain why it is inert here. */
export function createDispatcher(deps: DispatcherDeps) {
  const lastNotified = new Map<string, number>();
  const bound = (c: KeymapCommand): string => deps.bindings?.get(c.id) ?? c.defaultBinding;
  return (e: KeyEventLike, activeContexts: ReadonlySet<string>): DispatchResult => {
    const got = eventBinding(e);
    const active = KEYMAP.filter((c) => activeContexts.has(c.context));
    const exact = active.find((c) => bound(c) === got);
    if (exact && deps.isValid(exact)) {
      deps.execute(exact);
      return { status: "executed", commandId: exact.id };
    }
    // A range binding (`Alt+1..9`, E10-S01 S5) runs only when its handler is valid. It is never
    // inert: a bare-digit range (`1..9`, Chart) would otherwise explain itself on every digit typed.
    const ranged = exact ? undefined : active.find((c) => rangeDigit(bound(c), got) !== null);
    if (ranged && deps.isValid(ranged)) {
      deps.execute(ranged, rangeDigit(bound(ranged), got) ?? undefined);
      return { status: "executed", commandId: ranged.id };
    }
    const target = exact ?? KEYMAP.find((c) => bound(c) === got);
    if (!target) return { status: "unbound" };
    deps.countInert?.(target.id);
    const t = deps.now();
    const prev = lastNotified.get(target.id);
    const notified = prev === undefined || t - prev >= INERT_NOTICE_WINDOW_MS;
    if (notified) {
      lastNotified.set(target.id, t);
      deps.notify(inertMessage(target));
    }
    return { status: "inert", commandId: target.id, notified };
  };
}
