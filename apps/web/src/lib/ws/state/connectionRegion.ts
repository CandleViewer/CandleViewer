// E10-S04 (#306) slice 4a: what the CMP-077 connection region (SCR-152) shows, pure over `WsState`
// and a clock (the 1 Hz tick is the caller's). Sources: E17-D02 §6 (states, routing rows 1–5),
// §10 B / D / F / R (verbatim; PROPOSED = the merged spec's nearest string, ruling on #306), §11
// (announcements); E17-D01 §4.1 T4. The component and its mount wait for E10-S01 (#304).
import type { OfflineCause, WsState } from "./types";

/** E17-D01 §4.1 T4: the OS notification (§11 row 11), the age-line step (§10 B5), long-outage (§10 B6). */
export const T4_NOTIFY_MS = 10_000;
export const T4_STEP_MS = 30_000;
export const T4_ESCALATE_MS = 300_000;

export type RegionState =
  "reconnecting" | "offline" | "session-ended" | "long-outage" | "read-only";
/** What the region is about; a change of it is what announces (§11). R1–R7: §10 R. */
export type ReadOnlyReason =
  "R1-shutdown" | "R2-kill-switch" | "R5-private-down" | "R6-system-unknown";
export type RegionReason = "disconnected" | "fatal" | "session" | ReadOnlyReason;

export interface ConnectionRegionView {
  readonly state: RegionState;
  readonly reason: RegionReason;
  readonly title: string;
  /** L1, L2; a read-only reason's one line is what still works. Ages are `aria-live="off"` (§11 row 10). */
  readonly lines: readonly string[];
  readonly controls: readonly ("retry" | "sign-in" | "details")[];
  /** "Next try in ~4 s" / "Connecting…" and its seconds; `null`: none (a shell cause until G11, §6). */
  readonly countdown: string | null;
  readonly countdownS: number | null;
  /** "00:12": the last data's age; `null` when the session had none. */
  readonly lastDataAgo: string | null;
  /** T4 30 s: the age line in `color.status.danger.strong` (§10 B5). */
  readonly ageEmphasis: boolean;
  /** T4 10 s: the once-per-episode OS notification is due (§11 row 11; the caller sends it once). */
  readonly notifyDue: boolean;
}

/** Inputs `WsState` does not carry. */
export interface RegionExtras {
  /** §6 row 5 R5: past the 10 s hand-over, the shell store's `degraded.privateHandedOver` (SCR-153 row 9). */
  readonly privateFeedDown?: boolean;
}

const ORDERS_OFF = "New orders off; cancel and close remain available, confirmed over the server.";
const STOPS = "Exchange-side stops still protect open positions; app-managed rules are paused.";
/** §10 D, the shell causes; `fatal` never reaches here (B-1). */
const SHELL: Readonly<Record<Exclude<OfflineCause, "fatal">, string>> = {
  tailnet_unreachable: "Not connected to the tailnet",
  offline: "You're offline",
  backend_unreachable: "Can't reach the server",
};
/** §10 F, the fatal closes the shipped client stops on (`closePolicy.ts`); 4403 is `session-ended`. */
const FATAL: Readonly<Record<number, string>> = {
  1002: "Can't connect — the app and the server disagree on the protocol. Copy details and report a bug.",
  1009: "Can't connect — a message was too large. Copy details and report a bug.",
  4400: "Can't connect — repeated protocol errors. Copy details and report a bug.",
};
/** PROPOSED: §10 B4's pattern with no F sentence (a fatal close with no code). */
const FATAL_UNKNOWN = "Can't connect. Copy details and report a bug.";
const SESSION_STOPS =
  "Exchange-side stops still protect open positions; app-managed rules are paused — sign in again to cancel or close.";
/** §10 F, a bare 4403 (no `bye` reason reaches the client until G12). */
const ACCESS_REMOVED = "Your access was removed — contact the owner";
const READ_ONLY: Readonly<Record<ReadOnlyReason, readonly [string, string]>> = {
  // PROPOSED: §10 R1 without the release, which the reducer does not keep (server prose).
  "R1-shutdown": [
    "Order entry off — backend restarting",
    "Cancel and close still work; exchange-side stops still protect open positions; app-managed rules are paused.",
  ],
  // PROPOSED: §10 R2 without "at 14:02 UTC", which `KillSwitchView` does not keep.
  "R2-kill-switch": ["Order entry off — trading frozen by the owner.", "Cancel still works."],
  "R5-private-down": [
    "Order entry off — private feed down; fills cannot be seen live.",
    "Cancel and close still work, confirmed over REST.",
  ],
  "R6-system-unknown": [
    "Order entry off — kill-switch status unknown until the server reports it.",
    "Cancel and close still work.",
  ],
};

const pad = (n: number): string => String(n).padStart(2, "0");
/** "00:12", "04:32"; PROPOSED past an hour: "1:05:03" (§10 has no hour form). */
export function formatAge(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const mmss = `${pad(m)}:${pad(total % 60)}`;
  return h > 0 ? `${h}:${mmss}` : mmss;
}

type Control = "retry" | "sign-in" | "details";
const RETRY: readonly Control[] = ["retry", "details"];
const view = (
  state: RegionState,
  reason: RegionReason,
  title: string,
  lines: readonly string[],
  controls: readonly Control[],
  more: Partial<ConnectionRegionView> = {},
): ConnectionRegionView => ({
  state,
  reason,
  title,
  lines,
  controls,
  countdown: null,
  countdownS: null,
  lastDataAgo: null,
  ageEmphasis: false,
  notifyDue: false,
  ...more,
});

function readOnlyReason(ws: WsState, extras: RegionExtras): ReadOnlyReason | null {
  if (ws.shutdown !== null) return "R1-shutdown"; // routing row 3
  if (ws.killSwitch.state === "engaged") return "R2-kill-switch"; // row 4
  if (extras.privateFeedDown === true) return "R5-private-down"; // row 5, in §6's order
  // Row 18 once the stream is no longer awaited; while `pending` it is reconciling (§2 row 16).
  const unknown = ws.killSwitch.state === "unknown" && ws.systemStream !== "pending";
  return unknown ? "R6-system-unknown" : null;
}

/** The region for this state at `nowMs`, or `null`: the slot is empty (live, or a session start). */
export function connectionRegion(
  ws: WsState,
  nowMs: number,
  extras: RegionExtras = {},
): ConnectionRegionView | null {
  const { link, outage } = ws;
  if (link.kind === "up") {
    const reason = readOnlyReason(ws, extras);
    if (reason === null) return null;
    const [title, stillWorks] = READ_ONLY[reason];
    return view("read-only", reason, title, [stillWorks], ["details"]);
  }
  if (outage === null && link.kind === "connecting") return null; // §11 row 15: nothing to freeze yet
  const lastDataMs = outage?.lastDataMs ?? null;
  const lastDataAgo = lastDataMs === null ? null : formatAge(nowMs - lastDataMs);
  const outageMs = outage === null ? -Infinity : nowMs - outage.sinceMs;
  const timing = {
    lastDataAgo,
    ageEmphasis: outageMs >= T4_STEP_MS,
    notifyDue: outageMs >= T4_NOTIFY_MS,
  };
  if (link.kind === "offline" && link.cause === "fatal") {
    if (link.closeCode === 4403) {
      const lines = [`${ACCESS_REMOVED}.`, SESSION_STOPS];
      return view(
        "session-ended",
        "session",
        "Session ended",
        lines,
        ["sign-in", "details"],
        timing,
      );
    }
    const l1 = (link.closeCode === undefined ? undefined : FATAL[link.closeCode]) ?? FATAL_UNKNOWN;
    const lines = [l1, `${ORDERS_OFF} ${STOPS}`];
    return view("offline", "fatal", "Offline — retry stopped", lines, RETRY, timing);
  }
  const escalated = outageMs >= T4_ESCALATE_MS;
  const state = escalated ? "long-outage" : "reconnecting";
  let title = "Disconnected — reconnecting"; // a shell cause; `connecting` has no counter (PROPOSED)
  if (escalated) title = `Disconnected for ${formatAge(outageMs)} — escalated`;
  if (link.kind === "offline" && link.cause !== "fatal") {
    const cause = SHELL[link.cause];
    // §10 B1b (PROPOSED there); without an age, the D sentence alone.
    const l1 = lastDataAgo === null ? `${cause}.` : `${cause} — last data ${lastDataAgo} ago.`;
    return view(state, "disconnected", title, [l1, `${ORDERS_OFF} ${STOPS}`], RETRY, timing);
  }
  // PROPOSED: with no data this session, L1 drops its "Last data … ago." sentence.
  const l1 = lastDataAgo === null ? ORDERS_OFF : `Last data ${lastDataAgo} ago. ${ORDERS_OFF}`;
  const disconnected = (more: Partial<ConnectionRegionView>) =>
    view(state, "disconnected", title, [l1, STOPS], RETRY, { ...timing, ...more });
  // `connecting`: the attempt's socket is opening, "Connecting…" (PROPOSED, §10 A).
  if (link.kind !== "reconnecting") return disconnected({ countdown: "Connecting…" });
  const countdownS = Math.max(1, Math.ceil((link.nextAttemptAtMs - nowMs) / 1000));
  if (!escalated) title = `Disconnected — reconnecting (${link.attempt})`;
  return disconnected({ countdown: `Next try in ~${countdownS} s`, countdownS });
}

export interface RegionAnnouncement {
  readonly politeness: "assertive";
  readonly text: string;
}

const EPISODE: ReadonlySet<RegionReason> = new Set(["disconnected", "fatal", "session"]);
const SPOKEN: Partial<Record<RegionReason, string>> = {
  disconnected:
    "Disconnected. New orders off. Cancel and close still work, confirmed over the server. Exchange-side stops still protect open positions.",
  fatal:
    "Offline — retry stopped. New orders off. Cancel and close still work, confirmed over the server.",
  session: `${ACCESS_REMOVED}.`,
};

/**
 * §11: what the region announces when its view goes from `prev` to `next`, or `null`. Keyed on the
 * reason, never on ticks: ages, counters and countdowns are `aria-live="off"` (row 10).
 * Row 1: entering a Disconnected episode, once; the attempt cycle and the T4 steps say nothing.
 * Row 14: `offline` `fatal` or `session-ended`, from any state. Row 2: a read-only reason change,
 * "Order entry off — {message}. {what still works}."
 */
export function regionAnnouncement(
  prev: ConnectionRegionView | null,
  next: ConnectionRegionView | null,
): RegionAnnouncement | null {
  if (next === null || prev?.reason === next.reason) return null;
  // A retry after a stop is no new episode.
  if (next.reason === "disconnected" && prev !== null && EPISODE.has(prev.reason)) return null;
  const title = next.title.endsWith(".") ? next.title : `${next.title}.`;
  return { politeness: "assertive", text: SPOKEN[next.reason] ?? [title, ...next.lines].join(" ") };
}
