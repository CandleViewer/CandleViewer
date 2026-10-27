import { useEffect, useRef, useState, type JSX } from "react";
import type { ConnectionState } from "../../shell/bootstrap/store.js";
import { useShellSelector } from "../../shell/useShellSelector.js";
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
 * CMP-076's container (#304 S3), `ShellConnectionSlot`'s content, on `useShellSelector`. It
 * announces nothing: E17-D02 §11 rows 1 and 14 are CMP-077's (the region container,
 * `ConnectionRegionSlot`, #306 slice 4b), and the chip has no row of its own (row 5's Delayed entry
 * is the host panel's; ages and latency are row 10's "never").
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
