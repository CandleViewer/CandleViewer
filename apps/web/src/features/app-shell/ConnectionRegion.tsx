import type { CSSProperties, JSX } from "react";
import { Button, Icon } from "@candleviewer/ui";
import type { ConnectionRegionView } from "../../lib/ws/state/connectionRegion";

export interface ConnectionRegionProps {
  readonly view: ConnectionRegionView;
  /** `session-ended`: SCR-001 through the auth path (E17-D02 §6 `onSignIn`). */
  readonly onSignIn: () => void;
  /**
   * `Retry now` (#304 S10, BQ-07; `15` CMP-077 `onRetryNow`): one manual handshake, never a loop.
   * Without it no button is drawn; a view without the `retry` control (`session-ended`, read-only)
   * draws none either.
   */
  readonly onRetryNow?: (() => void) | undefined;
  /** A handshake is under way: the button stays, focusable and busy, and does nothing. */
  readonly retrying?: boolean;
}

const BOX: CSSProperties = {
  display: "flex",
  flexWrap: "wrap", // at 320 CSS px the buttons go under the text, never squeeze it (SC 1.4.10)
  alignItems: "flex-start",
  gap: "var(--space-inset-sm)",
  padding: "var(--space-inset-sm)",
  borderLeft: "calc(var(--border-thick) * 1px) solid var(--border-ink)",
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
 * F / R). An E10 shell organism (#306): apps/web is its home, moving to packages/ui only if a
 * second feature consumes it; props are the slice 4a view, not the catalogue props.
 *
 * It follows E17-D02 §6's non-modal region, not the earlier modal overlay reading (`14` §0 item 4
 * still says "reconnect overlay"; a carry for the next catalogue touch). A `region` named
 * "Connection": no focus trap, a state change never moves focus, and it **owns no live region** —
 * the container writes §11 through the shell announcer. The countdown and ages are
 * `aria-live="off"` (§11 row 10).
 *
 * In the banner slot below the TopBar (§4.1), so it never covers SCR-063's cancel / close or
 * CMP-211; it pushes the workspace down rather than overlaying it.
 *
 * `Retry now` (#304 S10, BQ-07 (b)): `WsClient.retryNow()`, the WS worker's `retry` port message;
 * a native button (Enter / Space), busy while a handshake is under way so focus never drops, and
 * never drawn for `session-ended` (4403: sign in again).
 * Deferred (carried to E17-Q04 #569): `Details` and its Owner / Viewer split (no diagnostics copy
 * spec yet) and `recovered`. Also deferred: `unstable`, "Back in ~N s" on R1 (`WsState` keeps no
 * notice time), and the long-outage outlined pill (the button keeps its secondary look).
 * Gap: the fatal L1 keeps §10 F's verbatim "Copy details and report a bug.", but no Details / Copy
 * details control exists until `Details` lands.
 * Visual deviations, deferred: the left border is `border.thick` (2 px),
 * not §4.1's 4 px (no 4 px border token); no 96 px min-height (§4.1, §13.2: no size token), so the
 * region is as tall as its text; the §4.1 pixel offsets and `color.text.secondary` body lines.
 */
export function ConnectionRegion({
  view,
  onSignIn,
  onRetryNow,
  retrying = false,
}: ConnectionRegionProps): JSX.Element {
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
      <div style={{ flex: "1 1 12em", minWidth: 0 }}>
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
      {onRetryNow !== undefined && view.controls.includes("retry") ? (
        <Button variant="secondary" size="sm" loading={retrying} onClick={onRetryNow}>
          Retry now
        </Button>
      ) : null}
      {view.controls.includes("sign-in") ? (
        <Button variant="primary" size="sm" onClick={onSignIn}>
          Sign in
        </Button>
      ) : null}
    </section>
  );
}
