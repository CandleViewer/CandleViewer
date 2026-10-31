import {
  KEYMAP,
  composesCharacter,
  eventBinding,
  isBareBinding,
  type KeyEventLike,
  type KeymapCommand,
} from "./keymap";
import { buildComboMap, ignoresRepeat, runsInEditable } from "./registry";
import { isPermanentlyReserved } from "./validate";

export const INERT_NOTICE_WINDOW_MS = 5000;

export type DispatchResult =
  | { readonly status: "executed"; readonly commandId: string }
  /** A held key's auto-repeat, taken and not run: its command runs once per press (`ignoreRepeat`). */
  | { readonly status: "repeat"; readonly commandId: string }
  | { readonly status: "inert"; readonly commandId: string; readonly notified: boolean }
  /** `Ctrl+K` with no palette yet: taken (default prevented) and never reported (BQ-7, D9). */
  | { readonly status: "reserved"; readonly binding: string }
  /** A key A-D05-2's rule leaves alone: neither run nor reported, its default not prevented. */
  | { readonly status: "ignored"; readonly reason: "composing" | "prevented" | "editable" }
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

const EDITABLE_ROLES = new Set(["combobox", "searchbox", "textbox"]);

/** A text-entry target (A-D05-2): input, textarea, select, contenteditable, or a combobox, searchbox or textbox. */
export function isEditableTarget(target: EventTarget | null | undefined): boolean {
  if (!(target instanceof Element)) return false;
  const field =
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement;
  if (field || EDITABLE_ROLES.has(target.getAttribute("role") ?? "")) return true;
  if (target instanceof HTMLElement && target.isContentEditable) return true;
  const host = target.closest("[contenteditable]"); // jsdom has no isContentEditable
  return host !== null && host.getAttribute("contenteditable") !== "false";
}

/**
 * Bare navigation keys are never reported, in any context (D6, ruled option (c)): Tab, Enter, Space and the arrows,
 * Shift aside, move focus, activate, scroll or move inside a widget wherever they are pressed. Nor is Esc, the
 * universal cancel (D7).
 */
const NAVIGATION_KEYS = new Set(["Tab", "Enter", "Space", "←", "→", "↑", "↓"]);
const neverReported = (binding: string): boolean =>
  binding === "Esc" || NAVIGATION_KEYS.has(binding.replace(/^Shift\+/, ""));

/** Contextual explanation: what the command needs and where its visible control lives. */
export function inertMessage(c: KeymapCommand): string {
  const where = typeof c.visibleControl === "string" ? ` Use ${c.visibleControl} instead.` : "";
  const ctx = c.context === "Global" ? "" : ` (${c.context} view)`;
  return `${c.label} is not available here${ctx}: it needs ${c.validWhen}.${where}`;
}

/**
 * Resolve key → command → `validWhen` → run, or explain why it is inert here (E49-S07), under A-D05-2's rule (#305):
 * a key an IME is composing never fires; a bare binding (no Ctrl, Alt or function key) is neither run nor reported on
 * a `defaultPrevented` event; in a text field a bare binding, or a character Option or AltGr composes, is never
 * reported and runs only if its command opts in (`allowInEditable`). Global resolves first, with a declared shadow
 * before the Global (AC1, BQ-4); the first command that can run takes the key, once per press unless it is a stepper.
 * An inert key explains itself from any context, as E49-S07 shipped, except a bare navigation key (Tab, Enter, Space,
 * the arrows: D6, ruled option (c)), Esc (D7), a range binding and a held key's repeat; `Ctrl+K`, reserved for the
 * palette, is taken without a notice until E15 registers the palette on it (BQ-7, D9).
 */
export function createDispatcher(deps: DispatcherDeps) {
  const lastNotified = new Map<string, number>();
  const map = buildComboMap(KEYMAP, deps.bindings);
  return (e: KeyEventLike, activeContexts: ReadonlySet<string>): DispatchResult => {
    if (e.isComposing === true || e.keyCode === 229) {
      return { status: "ignored", reason: "composing" };
    }
    const got = eventBinding(e);
    const bare = isBareBinding(got);
    if (bare && e.defaultPrevented === true) return { status: "ignored", reason: "prevented" };
    const typing = (bare || composesCharacter(e)) && isEditableTarget(e.target);
    const hits = map.resolve(got, activeContexts);
    for (const { command, digit } of hits) {
      if ((typing && !runsInEditable(command)) || !deps.isValid(command)) continue;
      if (e.repeat === true && ignoresRepeat(command)) {
        return { status: "repeat", commandId: command.id };
      }
      deps.execute(command, digit);
      return { status: "executed", commandId: command.id };
    }
    if (typing) return { status: "ignored", reason: "editable" };
    const inert = hits.find((h) => h.digit === undefined)?.command ?? map.anywhere(got);
    if (inert === undefined || neverReported(got)) return { status: "unbound" };
    if (isPermanentlyReserved(got)) return { status: "reserved", binding: got };
    if (e.repeat === true) return { status: "inert", commandId: inert.id, notified: false };
    deps.countInert?.(inert.id);
    const t = deps.now();
    const prev = lastNotified.get(inert.id);
    const notified = prev === undefined || t - prev >= INERT_NOTICE_WINDOW_MS;
    if (notified) {
      lastNotified.set(inert.id, t);
      deps.notify(inertMessage(inert));
    }
    return { status: "inert", commandId: inert.id, notified };
  };
}
