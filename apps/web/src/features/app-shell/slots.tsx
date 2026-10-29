/**
 * Shell slots (E10-S01 S1, #304). The contract for content that later slices put into the shell
 * chrome without editing it:
 *
 * - `ShellBannerSlot`: one full-width row between the top bar and the canvas (D03 §2, 0 px when
 *   empty). It has no landmark of its own; a banner brings its own role (`status` / `alert`).
 *   #306 fills it with `ShellBanner`: the CMP-077 connection region (SCR-152), then CMP-092.
 * - `ShellConnectionSlot`: inside the header (`banner`) landmark. S3 fills it with the CMP-076 chip
 *   and the shell's live-region pair (`ConnectionStatusSlot`).
 * - `ShellCanvasOverlaySlot`: a positioned sibling of the route outlet inside `main`, covering the
 *   visible canvas. It never wraps or re-renders the outlet. Its layer ignores the pointer, so
 *   overlay content that takes input sets `pointer-events: auto` itself. #306 fills it with
 *   SCR-159's in-canvas states (`OfflineOverlay`).
 * - `ShellPanicSlot`: the reserved Safety-cluster position at the TopBar's right (E10-D02 ruling 1,
 *   E10-D03 C5) for the CMP-211 PanicButtons organism, which E39-S05 builds. `ShellPanicMount`
 *   below types what that organism resolves itself. Until it lands the slot renders nothing: no node, no Tab stop, no
 *   stand-in control (a Flatten / Cancel / Freeze button that does nothing is a false affordance).
 * - `ShellStatusSlot`: inside the footer (`contentinfo`) landmark: S4's CMP-208 status bar.
 * - `ShellBarCloseSlot`: the status bar's bar-close countdown; the chart features fill it.
 *
 * Each slot renders nothing until a later slice (#306 slices 3 and 4b) fills it by editing only
 * this file. A slot reads its own state; it takes no props from the layout, so filling one never
 * re-renders the outlet.
 */
import type { JSX } from "react";
import type { MeClaims } from "../../routes/rbac";
import { OfflineOverlay } from "../system-states/OfflineOverlay";
import { ShellBanner } from "./banner";
import { ConnectionStatusSlot } from "./ConnectionStatusSlot";
import { StatusBar } from "./StatusBar";

/** A shell slot: a prop-less component that renders its content or nothing. */
export type ShellSlot = () => JSX.Element | null;

/** #306: the CMP-077 region, then the CMP-092 degraded banner below it (`ShellBanner`). */
export const ShellBannerSlot: ShellSlot = ShellBanner;

export const ShellConnectionSlot: ShellSlot = ConnectionStatusSlot;

/** #306 slice 9: SCR-159's offline and tailnet-unreachable pages over the canvas. */
export const ShellCanvasOverlaySlot: ShellSlot = OfflineOverlay;

/** CMP-211's three actions, in Tab order (E39-D03 §5): FLATTEN ALL… → CANCEL ALL… → FREEZE…. */
export type PanicAction = "flatten" | "cancel" | "kill";

/**
 * The reason keys a CMP-211 leg resolves to (E10-D03 §1.3). The `rbac.*` keys are E09-D09 §3.1's,
 * verbatim. E10-D03 G20/G14 propose `health.*` for E17-D01 §7; not yet registered — E39-S05
 * derives the type from the registered vocabulary once it lands.
 */
export type PanicReasonKey =
  | "rbac.view_as"
  | "rbac.permission"
  | "rbac.owner_only"
  | "health.offline"
  | "health.protocol_incompatible";

/** One gating leg of a button; legs run in E09-D09 §2.1 step 3 order and the first refusal wins. */
export interface PanicReasonLeg {
  readonly leg: "view_as" | "role" | "owner_only" | "health";
  readonly key: PanicReasonKey;
  /** `view_as` refuses only the global-scope freeze and Release… (the C-2.6 carve-out). */
  readonly onlyOn?: "global-freeze-and-release";
}

/** One button's gating inputs: the permission its role leg reads, its legs, its reason node. */
export interface PanicLeg {
  /** The `x-rbac` permission of the button's endpoint, read from the claims' permission set. */
  readonly permission: "positions:write" | "orders:write" | "killswitch:write";
  readonly reasons: readonly PanicReasonLeg[];
  /** id of the button's own reason node: in the DOM at mount, linked by `aria-describedby`. */
  readonly reasonNodeId: string;
}

/**
 * The inputs the CMP-211 organism resolves for itself inside `ShellPanicSlot`. The slot keeps the
 * shell rule (no props from the layout, so filling it never re-renders the outlet): the organism
 * reads `claims` from the `/me` cache and compares `PanicLeg.permission` against
 * `claims.permissions` (never a role name, E09-D09 §2.1); it reads `scope` from the TopBar's
 * CMP-105 selector, the view-as context from `GET /auth/session/view-as` (E09-D09 §3.1), and the
 * health inputs (server reachability and the protocol state) for the `health.*` legs.
 * It wraps each leg in CMP-079 RbacGate (T2: `aria-disabled`, stays in the Tab order).
 * An enabled or T2-disabled leg is a rendering hint only; the server's 403 is the truth and an
 * enabled button grants nothing.
 * E39-S05 KEEPS the Ctrl+Shift+K reservation in `keymap/reserved-keys.json` and adds
 * `reservedOverride.rationale` to its `risk.kill_switch_open` entry; it does not remove the
 * reservation.
 */
export interface ShellPanicMount {
  /** CMP-211 `scope` (`15`). A manager on `global` gets `rbac.owner_only`. */
  readonly scope: "account" | "group" | "global";
  readonly claims: MeClaims;
  /** One reason node per button, never an aggregate line (E10-D03 CMP-211 row, C25). */
  readonly legs: Readonly<Record<PanicAction, PanicLeg>>;
}

const ROLE: PanicReasonLeg = { leg: "role", key: "rbac.permission" };
const OWNER_ONLY: PanicReasonLeg = { leg: "owner_only", key: "rbac.owner_only" };
const HEALTH: readonly PanicReasonLeg[] = [
  { leg: "health", key: "health.offline" },
  { leg: "health", key: "health.protocol_incompatible" },
];

/** E10-D03 §1.3's two Safety-cluster rows. View-as never gates FLATTEN ALL… or CANCEL ALL…. */
export const PANIC_LEGS: ShellPanicMount["legs"] = {
  flatten: {
    permission: "positions:write",
    reasons: [ROLE, OWNER_ONLY, ...HEALTH],
    reasonNodeId: "cv-panic-reason-flatten",
  },
  cancel: {
    permission: "orders:write",
    reasons: [ROLE, OWNER_ONLY, ...HEALTH],
    reasonNodeId: "cv-panic-reason-cancel",
  },
  kill: {
    permission: "killswitch:write",
    reasons: [
      { leg: "view_as", key: "rbac.view_as", onlyOn: "global-freeze-and-release" },
      ROLE,
      OWNER_ONLY,
      ...HEALTH,
    ],
    reasonNodeId: "cv-panic-reason-kill",
  },
};

/** Empty until E39-S05 fills it with the CMP-211 organism; renders nothing, takes no focus. */
export const ShellPanicSlot: ShellSlot = () => null;

export const ShellBarCloseSlot: ShellSlot = () => null;

export const ShellStatusSlot: ShellSlot = () => <StatusBar barClose={<ShellBarCloseSlot />} />;
