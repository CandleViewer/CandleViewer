import type { CSSProperties, JSX, ReactNode } from "react";
import { Icon, type IconName } from "@candleviewer/ui";
import type { ConnectionState, Environment } from "../../shell/bootstrap/store.js";
import { useShellSelector } from "../../shell/useShellSelector.js";
import type { LatencyState } from "../../lib/telemetry/latencyIndicator.js";
import { CLIENT_VERSION } from "../../lib/ws/protocol/frames.js";
import { VERSION_COPY } from "../system-states/copy";
import { checkVersion } from "../system-states/versionMismatch";
import { useUtcClock } from "./clock";

/** Visually hidden, read in browse mode (the standard clip pattern; not layout spacing). */
const HIDDEN: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  overflow: "hidden",
  clipPath: "inset(50%)",
  whiteSpace: "nowrap",
};

type Tone = "ok" | "warn" | "error" | "none";
const GLYPH: Record<Tone, IconName> = {
  ok: "check",
  warn: "warning",
  error: "danger",
  none: "info",
};
const INK: Record<Tone, string> = {
  ok: "var(--color-status-success-strong)",
  warn: "var(--color-status-warning-strong)",
  error: "var(--color-status-danger-strong)",
  none: "var(--color-text-secondary)",
};

/** Wraps at narrow widths (SC 1.4.10 at 320 px): no fixed widths, every item may shrink and wrap. */
const ROW: CSSProperties = {
  position: "relative",
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-1) var(--space-2)",
  minHeight: "var(--size-row-comfortable)",
  padding: "var(--space-2) var(--space-inset-sm)",
  background: "var(--color-surface-sunken)",
  borderTop: "calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
  color: "var(--color-text-primary)",
  fontSize: "var(--font-size-xs)",
  fontVariantNumeric: "tabular-nums",
};
const GROUP: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-1) var(--space-2)",
  minWidth: 0,
};
const CHIP: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: "var(--space-1)",
  minWidth: 0,
  overflowWrap: "anywhere",
};
const PUSH: CSSProperties = { marginLeft: "auto" };
const TERTIARY: CSSProperties = { color: "var(--color-text-tertiary)" };

interface ChipProps {
  readonly tone: Tone;
  /** The state in words, e.g. "WS latency: ok"; it changes only on a state transition. */
  readonly text: string;
  readonly kind: string;
}

/** A CMP-210 health chip as status text (no admin link yet): glyph + words, never colour alone. */
function Chip({ tone, text, kind }: ChipProps): JSX.Element {
  return (
    <span data-chip={kind} data-tone={tone} style={CHIP}>
      <span style={{ color: INK[tone], display: "inline-flex" }}>
        <Icon name={GLYPH[tone]} size="sm" />
      </span>
      <span>{text}</span>
    </span>
  );
}

const CONNECTION_WORD: Record<ConnectionState["kind"], readonly [string, Tone]> = {
  live: ["live", "ok"],
  connecting: ["connecting", "warn"],
  reconnecting: ["reconnecting", "error"],
  offline: ["offline", "error"],
};

/**
 * The WS health chip. It reads only the connection kind, so attempts and the 1 Hz latency never
 * re-render it. The store has no attempt count or last-data age for it to name. It is a DOM sibling
 * of the "System status" region, never live content: a connection transition is announced once,
 * assertively, by the connection region (CMP-077), not a second time politely here.
 */
function ConnectionChip(): JSX.Element {
  const kind = useShellSelector((s) => s.connection.kind);
  const [word, tone] = CONNECTION_WORD[kind];
  return <Chip kind="connection" tone={tone} text={`Connection: ${word}`} />;
}

const LATENCY_TONE: Record<LatencyState, Tone> = {
  ok: "ok",
  degraded: "warn",
  breach: "error",
  unavailable: "none",
};

/** The latency chip's live half: glyph + state word only, so a value-only update is silent. */
function LatencyStateChip(): JSX.Element {
  const state = useShellSelector((s) => s.latency.state);
  return <Chip kind="latency" tone={LATENCY_TONE[state]} text={`WS latency: ${state}`} />;
}

/**
 * The latency value, outside the live region: the eye reads "· 38 ms"; browse mode reads the
 * E10-D03 §10.2 name verbatim ("WS latency: ok, 38 ms", `latencyIndicator.ts`).
 */
function LatencyValue(): JSX.Element | null {
  const valueMs = useShellSelector((s) => s.latency.valueMs);
  const label = useShellSelector((s) => s.latency.label);
  if (valueMs === null) return null;
  return (
    <span data-latency-value="" style={{ color: "var(--color-text-secondary)" }}>
      <span aria-hidden="true">{`· ${valueMs} ms`}</span>
      <span style={HIDDEN}>{label}</span>
    </span>
  );
}

/** The UTC clock: the only 1 Hz leaf; never a live region (D02 :255). */
function UtcClock(): JSX.Element {
  return <span data-clock="">{useUtcClock()}</span>;
}

const ENV_WORD: Record<Environment | "unknown", string> = {
  live: "Live",
  demo: "Demo",
  testnet: "Testnet",
  unknown: "unknown",
};

/**
 * The ENV repeat. Stand-in: plain words from the store until CMP-075's badge is on `main`; an
 * unknown environment says so, never a defaulted Demo.
 */
function EnvRepeat(): JSX.Element {
  const env = useShellSelector((s) => s.environment);
  const word = ENV_WORD[env];
  return (
    <span data-env={env}>
      <span aria-hidden="true">{env === "unknown" ? "ENV UNKNOWN" : word.toUpperCase()}</span>
      <span style={HIDDEN}>{`Trading environment: ${word}`}</span>
    </span>
  );
}

/**
 * SCR-157's reminder after Later (E10-D03 §9.1, board 10; D02 :230's proposal, PROPOSED), until
 * the next launch: plain text beside the version, outside the live part, so it is never announced.
 */
function UpdateReminder(): JSX.Element | null {
  const shown = useShellSelector(
    (s) =>
      s.updateDeferred &&
      checkVersion(CLIENT_VERSION, s.serverProtocol, s.serverVersion) === "update_available",
  );
  return shown ? <Chip kind="update" tone="none" text={VERSION_COPY.label} /> : null;
}

export interface StatusBarProps {
  /** The bar-close countdown's slot; the chart features fill it. */
  readonly barClose?: ReactNode;
}

/**
 * CMP-208 StatusBar (E10-S01 S4, #304; E10-D03 §2.1), inside the shell's `contentinfo`. It holds
 * no state: each leaf subscribes to its own slice, so the 1 Hz clock and latency re-render only
 * their own leaf. Not here yet (no data source): recorder, rules armed, clock offset, CPU / FPS,
 * Kill switch… (E39). The live part is one labelled polite `role="status"` region (D02 :255,
 * E10-D03 §10.2) holding only the latency state words, so it speaks on a latency transition,
 * never on a value or a tick; the connection chip beside it, the latency value, the clock and the
 * bar-close countdown sit outside it.
 */
export function StatusBar({ barClose }: StatusBarProps): JSX.Element {
  return (
    <div style={ROW}>
      <div style={GROUP}>
        <ConnectionChip />
        <div role="status" aria-label="System status">
          <LatencyStateChip />
        </div>
        <LatencyValue />
      </div>
      <span style={PUSH}>
        <UtcClock />
      </span>
      <span data-shell-slot="bar-close">{barClose}</span>
      <UpdateReminder />
      <EnvRepeat />
      <span style={TERTIARY}>{`v${CLIENT_VERSION}`}</span>
    </div>
  );
}
