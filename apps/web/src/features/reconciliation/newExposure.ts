/**
 * New exposure, per account (E29-S07 #1028; BQ-7 of the ruling of record 6575172489, BQ-3 ruled
 * (6610918411)): one selector that answers "open" or a T2 reason key, and one guard every
 * new-exposure control calls before it sends, so a refused press sends nothing. E30-S01's Submit,
 * E31-S01's click-to-trade and E29-S02's quantity-up and trigger amends consume this API (BQ-3:
 * #912 wires its own call sites); this ticket wires only the keymap's arm-gated order entries.
 *
 * **Binding (6575172489):** no exit ever consults this — cancel, close, close all, a quantity
 * decrease, a stop's attach or tighten, and a take-profit's edit stay enabled in every state
 * (C-2.6; `24` §8.10). The server's gate decides (#5185); this selector only displays (C-12.4,
 * C-2.21).
 *
 * Legs, first missing wins (E09-D09 §2.1; E29-D03 §4.2 precedence):
 *  1. view-as: `rbac.view_as` (the caller passes the target's name; no store holds it yet).
 *  2. the transport, "blind": the link is not up (`feed.disconnected`, or `feed.unreachable` for a
 *     shell cause), `WsState.orderEntry` (`risk.frozen.submit`, `feed.shutdown`,
 *     `feed.system_unknown`) and R5's private feed (`feed.private_down`) — E17-D02 §10 J's keys,
 *     PROPOSED by their owner (E17-D01 §7, E39-D01). A refusal here is `order.blocked_offline`.
 *  3. the B19 lock: `recon.killlock` after the kill switch, else `recon.stale`; a reduce-only
 *     submit `recon.reduce`.
 *  4. the client pause: `recon.reconciling`, `recon.desync` — binding only this client, PROPOSED
 *     until E29-D03 OQ-4 closes.
 * The `recon.*` keys are PROPOSED to E09-D09 §3.1's owner (`32` G-T2.4); their strings are the
 * E29-D06 deck's (D03:336–340), typed here until E09-D09 registers the vocabulary.
 */
import { useSyncExternalStore } from "react";
import { getActiveClient } from "../../lib/ws/client/activeClient";
import { useWsState } from "../../lib/ws/client/useWsState";
import { INITIAL_WS_STATE } from "../../lib/ws/state/reducer";
import type { WsState } from "../../lib/ws/state/types";
import {
  shellAccountSignals,
  useShellAccountSignals,
  type AccountSignal,
} from "../../shell/accountState";
import { getShellState, subscribeShellState } from "../../shell/bootstrap/store";
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";
import { exposureAccountInScope, setExposureGuard } from "../../keymap/registry";

/** E29-D03 §5.3's OMS account-state vocabulary (D06 deck, PROPOSED to E09-D09 §3.1). */
export const RECON_REASONS = {
  "recon.reconciling": "Reconciling with Bybit — new orders are paused.",
  "recon.desync": "Data being verified — new orders are paused.",
  "recon.stale": "Stale — new orders locked until the owner resolves it.",
  "recon.killlock": "After the kill switch — new orders locked until resolved.",
  "recon.reduce": "Locked — reduce through Close position.",
} as const;
export type ReconReason = keyof typeof RECON_REASONS;

/** The transport's keys (E17-D02 §10 J; E39-D02 S25), PROPOSED by their owners. */
export const BLIND_REASONS = {
  "feed.disconnected": "Not connected — new orders off; cancel and close still work.",
  "feed.unreachable": "Can't reach the server — orders, cancel and close off.",
  "feed.shutdown": "Backend restarting — new orders off; cancel still works.",
  "feed.system_unknown": "Kill-switch status unknown — new orders off.",
  "feed.private_down": "Private feed down — new orders off; cancel still works.",
  "risk.frozen.submit": "Frozen — only the owner can release it.",
} as const;
export type BlindReason = keyof typeof BLIND_REASONS;

export type ExposureReason = "rbac.view_as" | BlindReason | ReconReason;

export type ExposureVerdict =
  | { readonly open: true }
  | { readonly open: false; readonly reason: ExposureReason; readonly text: string };

export interface ExposureInput {
  readonly ws: WsState;
  /** SCR-153 row 9's hand-over (`degraded.privateHandedOver`): R5. */
  readonly privateFeedDown: boolean;
  /** The account's shell state; `undefined` for no account (a control with none in scope). */
  readonly account: AccountSignal | undefined;
  readonly reduceOnly?: boolean;
  /** The view-as target's name while a view-as context is held, else `null`. */
  readonly viewingAs?: string | null;
  /** An account is in scope (legs 3–4 apply); `false` for a control with none. */
  readonly scoped?: boolean;
  /** The shell's account store refused a state past its bound: an unheld account reads closed. */
  readonly overflowed?: boolean;
}

const OPEN: ExposureVerdict = Object.freeze({ open: true });
const shut = (reason: ExposureReason, text: string): ExposureVerdict => ({
  open: false,
  reason,
  text,
});

function blind(ws: WsState, privateFeedDown: boolean): BlindReason | null {
  const { link } = ws;
  if (link.kind === "offline" && link.cause !== "fatal" && link.cause !== "backend_unreachable") {
    return "feed.unreachable";
  }
  if (link.kind !== "up") return "feed.disconnected";
  if (!ws.orderEntry.enabled) {
    if (ws.orderEntry.reason === "kill_switch_engaged") return "risk.frozen.submit";
    if (ws.orderEntry.reason === "shutdown_pending") return "feed.shutdown";
    return "feed.system_unknown";
  }
  return privateFeedDown ? "feed.private_down" : null;
}

/** The selector: "open", or the first missing leg's reason (pure; render-safe). */
export function newExposureGate(input: ExposureInput): ExposureVerdict {
  const target = input.viewingAs ?? null;
  if (target !== null) return shut("rbac.view_as", `Read-only while viewing as ${target}.`);
  const transport = blind(input.ws, input.privateFeedDown);
  if (transport !== null) return shut(transport, BLIND_REASONS[transport]);
  const oms = input.account?.oms ?? null;
  if (oms === null) {
    // Review fold m3: until the first `system` snapshot this connection has not heard the replay
    // (`23` §15.9), and past the store's bound an account it does not hold may be locked: both
    // read as reconciling (fail closed), never as open.
    const unheard = input.ws.systemStream === "pending";
    const unheld = input.overflowed === true && input.account === undefined;
    if (input.scoped === true && (unheard || unheld)) {
      return shut("recon.reconciling", RECON_REASONS["recon.reconciling"]);
    }
    return OPEN;
  }
  let reason: ReconReason;
  if (oms.state === "stale") {
    reason =
      input.reduceOnly === true ? "recon.reduce" : oms.killLock ? "recon.killlock" : "recon.stale";
  } else {
    reason = oms.state === "desync" ? "recon.desync" : "recon.reconciling";
  }
  return shut(reason, RECON_REASONS[reason]);
}

export interface ExposureScope {
  /** The account the control would place on; `null` when none is in scope (the legs 3–4 skip). */
  readonly accountId: string | null;
  readonly reduceOnly?: boolean;
  readonly viewingAs?: string | null;
}

const accountOf = (accountId: string | null): AccountSignal | undefined =>
  accountId === null
    ? undefined
    : shellAccountSignals.getSnapshot().accounts.get(accountId.toLowerCase());

/**
 * The guard a new-exposure control calls before it sends: the verdict at this moment, read from the
 * live client, the shell store and the shell's account states. A refusal by the transport is
 * recorded as `order.blocked_offline` on the page's `cv:analytics` seam (BQ-8 of 6575172489: no
 * account, symbol or figure; nothing leaves the page); any other refusal emits nothing (D03 C-18).
 */
export function guardNewExposure(scope: ExposureScope): ExposureVerdict {
  const verdict = newExposureGate({
    ws: getActiveClient()?.getState() ?? INITIAL_WS_STATE,
    privateFeedDown: getShellState().degraded.privateHandedOver,
    account: accountOf(scope.accountId),
    reduceOnly: scope.reduceOnly ?? false,
    viewingAs: scope.viewingAs ?? null,
    scoped: scope.accountId !== null,
    overflowed: shellAccountSignals.getSnapshot().overflowed,
  });
  if (!verdict.open && verdict.reason in BLIND_REASONS) {
    window.dispatchEvent(
      new CustomEvent(THEME_ANALYTICS_EVENT, {
        detail: { name: "order.blocked_offline", reason: verdict.reason },
      }),
    );
  }
  return verdict;
}

/** The selector as a hook: re-renders on a change of the link, the hand-over or the account. */
export function useNewExposureGate(scope: ExposureScope): ExposureVerdict {
  const ws = useWsState();
  const privateFeedDown = useSyncExternalStore(
    subscribeShellState,
    () => getShellState().degraded.privateHandedOver,
    () => getShellState().degraded.privateHandedOver,
  );
  const id = scope.accountId?.toLowerCase() ?? null;
  const account = useShellAccountSignals((s) => (id === null ? undefined : s.accounts.get(id)));
  const overflowed = useShellAccountSignals((s) => s.overflowed);
  return newExposureGate({
    ws,
    privateFeedDown,
    account,
    reduceOnly: scope.reduceOnly ?? false,
    viewingAs: scope.viewingAs ?? null,
    scoped: id !== null,
    overflowed,
  });
}

/**
 * Installs the guard for the keymap's arm-gated entries (`keymap/registry.ts`
 * `setExposureGuard`), from `App` beside `KeymapHost`, until the returned stop. The registry never
 * imports this module, so a keymap import does not pull in the WS client and the shell stores.
 */
export function installKeymapExposureGuard(): () => void {
  const verdict = (): ExposureVerdict => guardNewExposure({ accountId: exposureAccountInScope() });
  return setExposureGuard({
    allows: () => verdict().open,
    refusal: () => {
      const v = verdict();
      return v.open ? null : v.text;
    },
  });
}
