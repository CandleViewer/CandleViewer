/**
 * SCR-012, the command palette (E10-S05, #5236): CMP-059 mounted once, inside the authenticated shell (SCR-010), over
 * the route manifest and the keymap registry. `Ctrl+K` (`global.palette`) and the CMP-084 trigger share one open
 * state; on the public routes no handler is registered, so `Ctrl+K` stays taken and inert (`dispatcher.ts`).
 *
 * The palette only presents: a route goes to the router, where the guard runs, and a command id to `runCommand`, where
 * the arm (`armAllows`, BQ-5) and the handler's own server calls run. It never calls a handler, reads the arm or
 * step-up, or fires a dangerous command: that command's own confirmation does (E30 / E39). It makes no request and
 * writes no audit record (C-2.9 is met by the handlers it reaches, as for a key press).
 */
import { useEffect, useMemo, useRef, useSyncExternalStore, type JSX, type RefObject } from "react";
import { useNavigate } from "react-router";
import { CommandPalette, type PaletteCommand, type PaletteSection } from "@candleviewer/ui";
import { registerCommand } from "../../keymap/KeymapHost";
import { getBindings } from "../../keymap/profile";
import { keymapUser } from "../../keymap/session";
import { isCommandValid, runCommand } from "../../keymap/registry";
import { getMeClaims } from "../../lib/auth/meCache";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { announce, forget } from "../app-shell/announcer";
import { closeSymbolSearch } from "../symbol-search/searchSession";
import { countText, GROUPS, noResultsText, PALETTE_COPY, refusedText } from "./copy";
import { reportPalette, type PaletteVia } from "./paletteEvents";
import { buildIndex, emptyQuerySections } from "./rank";
import { readRecent, recordRun } from "./recent";
import {
  PALETTE_COMMAND,
  getPaletteSources,
  subscribePaletteSources,
  type PaletteRow,
  type SourceContext,
} from "./sources";

/** The open state and which opening it is: each opening reads the registry, the profile and the claims afresh. */
interface OpenState {
  readonly open: boolean;
  readonly epoch: number;
}
let state: OpenState = { open: false, epoch: 0 };
const listeners = new Set<() => void>();
const setOpen = (open: boolean): void => {
  if (state.open === open) return;
  state = { open, epoch: open ? state.epoch + 1 : state.epoch };
  listeners.forEach((l) => l());
};
const subscribeOpen = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
const getOpenState = (): OpenState => state;
/** Opened with focus on `body`: the Dialog has nowhere to return it, so the host gives it to `main` (WCAG 2.4.3). */
let openedFromBody = false;

/** `Ctrl+K` and the trigger: one toggle, so the key closes what the button opened. */
export function togglePalette(via: PaletteVia): void {
  const next = !state.open;
  if (next) {
    closeSymbolSearch(); // one modal at a time: SCR-102 closes (no commit) rather than stacking under SCR-012
    const active = document.activeElement;
    openedFromBody = active === null || active === document.body;
  }
  setOpen(next);
  if (next) reportPalette({ name: "palette.opened", via });
}

/** Closes the palette without running anything (tests, a host leaving the shell). */
export const closePalette = (): void => setOpen(false);

/** The refused-run sentence's one key in the shell announcer: forgotten before each, so each refusal is said once. */
const REFUSED_KEY = "palette:refused";

/** The query's length at run time, read from CMP-059's input (the primitive owns the query); never its text. */
const queryLength = (): number =>
  document.querySelector<HTMLInputElement>('[data-cmp="CMP-059"] [role="combobox"]')?.value.trim()
    .length ?? 0;

export function CommandPaletteHost({
  mainRef,
}: {
  readonly mainRef?: RefObject<HTMLElement>;
}): JSX.Element {
  const { open: shown, epoch } = useSyncExternalStore(subscribeOpen, getOpenState, getOpenState);
  const sources = useSyncExternalStore(subscribePaletteSources, getPaletteSources);
  // The claims change with `/me` (`bootstrap.ts` sets both): a change while open re-filters in place (`14` :85).
  const me = useShellSelector((s) => s.me);
  const navigate = useNavigate();
  /** What to run once the palette has closed and focus has returned (so a next dialog never opens under it). */
  const pending = useRef<(() => void) | null>(null);
  const navigated = useRef(false);

  useEffect(() => registerCommand(PALETTE_COMMAND, () => togglePalette("hotkey")), []);
  useEffect(
    () => () => {
      openedFromBody = false;
      setOpen(false);
    },
    [],
  );
  useEffect(() => {
    if (shown) return;
    const run = pending.current;
    pending.current = null;
    run?.();
    // Read and clear on every close, so a route run from a focused opener cannot leave the flag set for later.
    const wasRoute = navigated.current;
    navigated.current = false;
    if (!openedFromBody) return;
    openedFromBody = false;
    // A route change is followed by the shell's own move to the heading; otherwise, if focus is still nowhere, `main`.
    // "Nowhere" is body, or still inside the closing palette (a browser blurs the inert layer; jsdom does not).
    const active = document.activeElement;
    const nowhere =
      active === null ||
      active === document.body ||
      active.closest('[data-cmp="CMP-059"]') !== null;
    if (!wasRoute && nowhere) mainRef?.current?.focus();
  }, [shown, mainRef]);

  const rows = useMemo(() => {
    void epoch; // rebuilt per opening; the rows stay put while the dialog fades out
    void me; // and per claims change
    const ctx: SourceContext = {
      claims: getMeClaims(),
      bindings: getBindings(),
      isValid: isCommandValid,
      viewAs: null, // no client view-as source yet (#304 gap 13)
    };
    return buildIndex(sources, ctx);
  }, [epoch, me, sources]);

  const symbolsSearched = sources.some((s) => s.group === GROUPS.symbol);

  const commands = useMemo(() => {
    const run = (row: PaletteRow): void => {
      const length = queryLength();
      setOpen(false);
      pending.current = () => {
        const { target } = row;
        if (target.kind === "route") {
          navigated.current = true;
          void navigate(target.path); // the guard runs there; focus follows the shell's route-change rule
        } else if (!isCommandValid(target.commandId) || !runCommand(target.commandId)) {
          // Not valid now (focus moved while closing), no handler, or an order entry while the arm reads unarmed:
          // nothing ran, and it is said once.
          forget(REFUSED_KEY);
          announce("polite", refusedText(row.label), REFUSED_KEY);
          return;
        }
        if (row.destructive === true) {
          // Only its own confirmation opened: nothing ran, so it is not recency and not a run (E10-D03 §6).
          reportPalette({
            name: "palette.chosen",
            id: target.kind === "route" ? row.id.slice("route:".length) : target.commandId,
            group: row.group,
            query_length: length,
          });
          return;
        }
        recordRun(keymapUser(), row.id); // ids and counts only, on this device, for this user
        reportPalette({
          name: "palette.ran",
          kind: target.kind,
          id: target.kind === "route" ? row.id.slice("route:".length) : target.commandId,
          group: row.group,
          query_length: length,
        });
      };
    };
    return rows.map((row): PaletteCommand => ({
      id: row.id,
      label: row.label,
      group: row.group,
      onRun: () => run(row),
      ...(row.shortcut === undefined ? {} : { shortcut: row.shortcut }),
      ...(row.disabledReason === undefined ? {} : { disabledReason: row.disabledReason }),
      ...(row.destructive === true ? { destructive: true } : {}),
    }));
  }, [rows, navigate]);

  const byId = useMemo(() => new Map(commands.map((c) => [c.id, c])), [commands]);

  // The empty query: Recent and Suggested, read at each opening (an empty section is dropped by CMP-059).
  const sections = useMemo((): readonly PaletteSection[] => {
    void epoch;
    const { recent, suggested } = emptyQuerySections(rows, readRecent(keymapUser()));
    const pick = (list: readonly PaletteRow[]): PaletteCommand[] =>
      list.flatMap((row) => byId.get(row.id) ?? []);
    return [
      { label: PALETTE_COPY.recent, commands: pick(recent) },
      { label: PALETTE_COPY.suggested, commands: pick(suggested) },
    ];
  }, [epoch, rows, byId]);

  return (
    <CommandPalette
      open={shown}
      onOpenChange={(next) => setOpen(next)}
      commands={commands}
      sections={sections}
      // A dangerous row: the palette closes, then `runCommand` reaches the handler, which opens its own confirm.
      onRequestConfirm={(command) => byId.get(command.id)?.onRun()}
      title={PALETTE_COPY.title}
      inputLabel={PALETTE_COPY.inputLabel}
      listLabel={PALETTE_COPY.listLabel}
      countText={countText}
      noResultsText={(query) => noResultsText(query, symbolsSearched)}
      confirmsTag={PALETTE_COPY.confirmsTag}
    />
  );
}
