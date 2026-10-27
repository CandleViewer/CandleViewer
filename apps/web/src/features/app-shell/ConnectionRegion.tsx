import type { CSSProperties, JSX } from "react";
import { Button, Icon } from "@candleviewer/ui";
import type { ConnectionRegionView } from "../../lib/ws/state/connectionRegion";

export interface ConnectionRegionProps {
  readonly view: ConnectionRegionView;
  /** `session-ended`: SCR-001 through the auth path (E17-D02 §6 `onSignIn`). */
  readonly onSignIn: () => void;
}

const BOX: CSSProperties = {
  pointerEvents: "auto", // the overlay layer ignores the pointer (slots.tsx); the region takes it back
  display: "flex",
  alignItems: "flex-start",
  gap: "var(--space-inset-sm)",
  padding: "var(--space-inset-sm)",
  borderBottom: "calc(var(--border-thick) * 1px) solid var(--border-ink)",
  boxShadow: "var(--elevation-chrome)",
  color: "var(--color-text-primary)",
  fontVariantNumeric: "tabular-nums",
};
const P: CSSProperties = { margin: 0 };

/**
 * Fill / border / ink per state (E17-D02 §6): danger subtle for Disconnected, the strong fill with
 * inverse text for long-outage, warning for read-only. The glyph pairs with the title, so colour is
 * never the only signal.
 */
function look(view: ConnectionRegionView): CSSProperties {
  if (view.state === "long-outage") {
    return {
      background: "var(--color-status-danger-strong)",
      color: "var(--color-text-inverse)",
      ["--border-ink" as string]: "var(--color-text-inverse)",
    };
  }
  const tone = view.state === "read-only" ? "warning" : "danger";
  return {
    background: `var(--color-status-${tone}-subtle)`,
    ["--border-ink" as string]: `var(--color-status-${tone}-strong)`,
  };
}

/**
 * CMP-077 ReconnectOverlay, the SCR-152 connection region (#306 slice 4b; E17-D02 §6, §10 B / D /
 * F / R). TEMPORARY: it lives in apps/web until E05's packages/ui CMP-077 replaces it (ruling on
 * #306); props are the slice 4a view, not the catalogue props.
 *
 * Non-modal `region` named "Connection": no focus trap, a state change never moves focus, and it
 * **owns no live region** — the container writes §11 through the shell announcer. The countdown
 * and ages are `aria-live="off"` (§11 row 10).
 *
 * Deferred: `Retry now` (B2; the WS client exposes no manual retry), `Details` and its Owner /
 * Viewer split (no role or diagnostics surface here yet), `recovered`, `unstable`, "Back in ~N s"
 * on R1 (`WsState` keeps no notice time), and the long-outage outlined pill (no retry button).
 */
export function ConnectionRegion({ view, onSignIn }: ConnectionRegionProps): JSX.Element {
  const strong = view.state === "long-outage";
  const ink = strong ? undefined : `var(--border-ink)`;
  // §10 B5: from T4 30 s the age line takes `color.status.danger.strong` (the strong fill keeps inverse).
  const ageInk = view.ageEmphasis && !strong ? "var(--color-status-danger-strong)" : undefined;
  return (
    <section
      aria-label="Connection"
      data-state={view.state}
      data-reason={view.reason}
      style={{ ...BOX, ...look(view) }}
    >
      <span style={{ display: "inline-flex", color: ink }}>
        <Icon name={view.state === "read-only" ? "warning" : "danger"} size="md" />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ ...P, fontWeight: 600 }}>{view.title}</p>
        {view.lines.map((line, i) => (
          <p key={line} style={{ ...P, color: i === 0 ? ageInk : undefined }}>
            {line}
          </p>
        ))}
        {view.countdown === null ? null : (
          <p aria-live="off" style={P}>
            {view.countdown}
          </p>
        )}
      </div>
      {view.controls.includes("sign-in") ? (
        <Button variant="primary" size="sm" onClick={onSignIn}>
          Sign in
        </Button>
      ) : null}
    </section>
  );
}
