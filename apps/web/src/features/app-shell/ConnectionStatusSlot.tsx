import { useEffect, useState, type JSX } from "react";
import type { ConnectionState } from "../../shell/bootstrap/store";
import { useShellSelector } from "../../shell/useShellSelector";
import { ConnectionStatus, type ConnectionChipStatus } from "./ConnectionStatus";
import { HIDDEN } from "./SkipLink";

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

export interface Announcement {
  readonly politeness: "assertive" | "polite";
  readonly text: string;
}

const LIVE_FAMILY: ReadonlySet<ConnectionChipStatus> = new Set(["live", "delayed", "stale"]);
/** E17-D02 §11 row 1, verbatim. */
const DISCONNECTED =
  "Disconnected. New orders off. Cancel and close still work, confirmed over the server. Exchange-side stops still protect open positions.";
/** §11 row 14 (PROPOSED there), verbatim. */
const RETRY_STOPPED =
  "Offline — retry stopped. New orders off. Cancel and close still work, confirmed over the server.";

/**
 * E17-D02 §11: assertive once per Disconnected episode (row 1; the attempt cycle says nothing) and
 * on a stopped retry (row 14); polite on entering / leaving `delayed` (E17-D01 §7; words PROPOSED).
 * A session start (row 15), ages, counters and latency never announce (row 10).
 */
export function chipAnnouncement(
  prev: ConnectionChipStatus | null,
  next: ConnectionChipStatus,
): Announcement | null {
  if (prev === null || prev === next) return null;
  if (next === "offline") return { politeness: "assertive", text: RETRY_STOPPED };
  if (next === "reconnecting") {
    return LIVE_FAMILY.has(prev) ? { politeness: "assertive", text: DISCONNECTED } : null;
  }
  if (next === "delayed" && LIVE_FAMILY.has(prev)) {
    return { politeness: "polite", text: "Connection rate reduced." };
  }
  if (prev === "delayed" && next === "live")
    return { politeness: "polite", text: "Connection live." };
  return null;
}

interface Track {
  readonly status: ConnectionChipStatus | null;
  readonly everLive: boolean;
  /** When the chip last left `live`, the last-data time (PROPOSED: the store has no `lastDataMs`). */
  readonly leftLiveAt: number | null;
  readonly said: (Announcement & { readonly seq: number }) | null;
}
const START: Track = { status: null, everLive: false, leftLiveAt: null, said: null };

/**
 * CMP-076's container (#304 S3), `ShellConnectionSlot`'s content, on `useShellSelector`. Beside the
 * chip it renders the shell's live-region pair (E17-D02 §11; `aria-live`, no role, so a screen's own
 * `status` / `alert` stays unique). A new message replaces the node, so each episode is announced.
 */
export function ConnectionStatusSlot(): JSX.Element {
  const connection = useShellSelector((s) => s.connection);
  const latencyMs = useShellSelector((s) => s.latency.valueMs);
  const [track, setTrack] = useState(START);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const chip = chipFromShell(connection, track.everLive);

  useEffect(() => {
    const now = Date.now();
    setNowMs(now);
    setTrack((t) => {
      if (t.status === chip.status) return t;
      const said = chipAnnouncement(t.status, chip.status);
      return {
        status: chip.status,
        everLive: t.everLive || chip.status === "live",
        leftLiveAt: t.status === "live" ? now : chip.status === "live" ? null : t.leftLiveAt,
        said: said === null ? t.said : { ...said, seq: (t.said?.seq ?? 0) + 1 },
      };
    });
  }, [chip.status]);

  const ticking = chip.status !== "live" && track.leftLiveAt !== null;
  useEffect(() => {
    if (!ticking) return undefined;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [ticking]);

  const { said } = track;
  const region = (live: Announcement["politeness"]): JSX.Element => (
    <div aria-live={live} aria-atomic="true" style={HIDDEN}>
      {said?.politeness === live ? (
        <p key={said.seq} data-seq={said.seq}>
          {said.text}
        </p>
      ) : null}
    </div>
  );
  return (
    <>
      <ConnectionStatus
        {...chip}
        lastGoodTs={chip.status === "live" ? null : track.leftLiveAt}
        latencyMs={latencyMs}
        nowMs={nowMs}
      />
      {region("polite")}
      {region("assertive")}
    </>
  );
}
