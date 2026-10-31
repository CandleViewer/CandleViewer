/**
 * The hotkey analytics (#305, BQ-10): the ticket's three events and `14` SCR-113's two, no other name, on the app's
 * analytics seam (`cv:analytics` on `window`, as SCR-157 and SCR-159 report; nothing leaves the page from here). An
 * event names commands, contexts and bindings only: never the user, and never a key typed in a text field, which the
 * dispatcher ignores before anything is counted (the ticket's Observability).
 */
import { THEME_ANALYTICS_EVENT } from "../shell/bootstrap/themeStore";
import { getCommand } from "./keymap";

export type HotkeyEvent =
  | {
      readonly name: "hotkey.rebound";
      readonly action: string;
      readonly from: string;
      readonly to: string;
    }
  | {
      readonly name: "hotkey.conflict_blocked";
      readonly action: string;
      readonly collidesWith: string;
    }
  | { readonly name: "hotkey.inert_pressed"; readonly action: string; readonly view: string }
  | { readonly name: "hotkey.reset" }
  | { readonly name: "hotkey.profile_imported" };

export function reportHotkey(event: HotkeyEvent): void {
  window.dispatchEvent(new CustomEvent<HotkeyEvent>(THEME_ANALYTICS_EVENT, { detail: event }));
}

/** `hotkey.rebound` for each of `ids` whose binding changed from `prev` to `next`; an unbound one is `""`. */
export function reportRebound(
  prev: ReadonlyMap<string, string>,
  next: ReadonlyMap<string, string>,
  ids: readonly string[],
): void {
  for (const action of ids) {
    const fallback = getCommand(action)?.defaultBinding ?? "";
    const from = prev.get(action) ?? fallback;
    const to = next.get(action) ?? fallback;
    if (from !== to) reportHotkey({ name: "hotkey.rebound", action, from, to });
  }
}
