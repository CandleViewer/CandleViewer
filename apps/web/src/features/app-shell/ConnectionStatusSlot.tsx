import { useEffect, useRef, useState, type JSX } from "react";
import type { ConnectionState } from "../../shell/bootstrap/store.js";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { announce, clearAnnouncements, CONNECTION_KEYS, forget } from "./announcer";
import { ConnectionStatus, type ConnectionChipStatus } from "./ConnectionStatus";

/**
 * The store's `connection` → the chip (E17-D02 §3, B-1). The store folds `fatal` into a shell cause,
 * so its `offline` is a running retry (`reconnecting`); it has no topic ages or throttle (S3 gaps).
 */
export function chipFromShell(
  c: ConnectionState,
  everLive: boolean,
): { status: ConnectionChipStatus; attempt?: number; firstConnect?: boolean } {
  if (c.kind === "live") return { status: "live" };
  if (c.kind === "reconnecting") return { status: "reconnecting", attempt: c.attempt };
  return c.kind === "connecting"
    ? { status: "reconnecting", firstConnect: !everLive }
    : { status: "reconnecting" };
}

type Row = keyof typeof CONNECTION_KEYS;
const LIVE_FAMILY: ReadonlySet<ConnectionChipStatus> = new Set(["live", "delayed", "stale"]);
/**
 * E17-D02 §11 rows 1 and 14, verbatim. Open question (raised to the owner, the §6 vs §10 B1b
 * class): row 1 says "Cancel and close still work", while §2 row 3 makes them T2 under a shell-cause
 * `offline` — which is every `offline` the store holds (REST is unreachable too).
 */
const TEXT: Record<Row, string> = {
  disconnected:
    "Disconnected. New orders off. Cancel and close still work, confirmed over the server. Exchange-side stops still protect open positions.",
  retryStopped:
    "Offline — retry stopped. New orders off. Cancel and close still work, confirmed over the server.",
};

/**
 * Which §11 row a chip move announces, or `null`. Row 1 on leaving a live value (the attempt cycle
 * says nothing; the announcer's key keeps it once per episode, CMP-077 included); row 14 on a
 * stopped retry, from any state. A session start (row 15), ages, counters and latency never
 * announce (row 10). Delayed's polite entry / exit (row 5) is the Delayed host panel's, not the chip's.
 */
export function chipAnnouncement(
  prev: ConnectionChipStatus | null,
  next: ConnectionChipStatus,
): Row | null {
  if (prev === null || prev === next) return null;
  if (next === "offline") return "retryStopped";
  return next === "reconnecting" && LIVE_FAMILY.has(prev) ? "disconnected" : null;
}

interface Track {
  readonly status: ConnectionChipStatus | null;
  readonly everLive: boolean;
  /**
   * `Date.now()` when the chip last left `live`; `null` while live or before the first live. It
   * stands in for the last-data time (PROPOSED: the store keeps no `lastDataMs`).
   */
  readonly leftLiveAt: number | null;
}
const START: Track = { status: null, everLive: false, leftLiveAt: null };

/**
 * CMP-076's container (#304 S3), `ShellConnectionSlot`'s content, on `useShellSelector`. It writes
 * rows 1 and 14 through the shell announcer and clears it on the return to live (the episode ends).
 */
export function ConnectionStatusSlot(): JSX.Element {
  const connection = useShellSelector((s) => s.connection);
  const latencyMs = useShellSelector((s) => s.latency.valueMs);
  const last = useRef(START);
  const [track, setTrack] = useState(START);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const chip = chipFromShell(connection, track.everLive);

  useEffect(() => {
    const prev = last.current;
    if (prev.status === chip.status) return;
    const now = Date.now();
    const row = chipAnnouncement(prev.status, chip.status);
    if (prev.status === "offline") forget(CONNECTION_KEYS.retryStopped); // row 14: once per entry
    if (row !== null) announce("assertive", TEXT[row], CONNECTION_KEYS[row]);
    if (chip.status === "live") clearAnnouncements();
    last.current = {
      status: chip.status,
      everLive: prev.everLive || chip.status === "live",
      leftLiveAt: prev.status === "live" ? now : chip.status === "live" ? null : prev.leftLiveAt,
    };
    setTrack(last.current);
    setNowMs(now);
  }, [chip.status]);

  const ticking = chip.status !== "live" && track.leftLiveAt !== null;
  useEffect(() => {
    if (!ticking) return undefined;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [ticking]);

  return (
    <ConnectionStatus
      {...chip}
      lastGoodTs={chip.status === "live" ? null : track.leftLiveAt}
      latencyMs={latencyMs}
      nowMs={nowMs}
    />
  );
}
