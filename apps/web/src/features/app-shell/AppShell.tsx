import type { CSSProperties, JSX, ReactNode, Ref } from "react";
import { SkipLink } from "./SkipLink";

/**
 * CMP-070 AppShell frame (E10-S01 S1, #304): props only, no router or store. It lives in apps/web
 * until the shell's presentational parts move to `packages/ui` (#304 plan §2).
 *
 * DOM order is the focus order of E10-D02 :254 (SkipLink → TopBar → NavRail → banner slot →
 * WorkspaceCanvas → RightRail → StatusBar); the grid places the banner row full width under the
 * top bar (E10-D03 §2). Landmarks per D02 :255: `banner`, `navigation` "Primary", `main`,
 * `complementary`, `contentinfo`. The top bar, rail, right rail and status bar are empty
 * placeholders until slices S2–S6 fill them.
 */
export interface AppShellProps {
  /** id of the one `main`, the skip link's target. */
  readonly mainId: string;
  readonly mainRef?: Ref<HTMLElement>;
  readonly connection?: ReactNode;
  readonly banner?: ReactNode;
  readonly canvasOverlay?: ReactNode;
  /** The route outlet. */
  readonly children: ReactNode;
}

const FRAME: CSSProperties = {
  position: "relative",
  display: "grid",
  gridTemplateAreas:
    '"header header header" "banner banner banner" "nav main aside" "footer footer footer"',
  gridTemplateRows: "auto auto minmax(0, 1fr) auto",
  gridTemplateColumns: "auto minmax(0, 1fr) auto",
  height: "100vh",
  background: "var(--color-surface-app)",
  color: "var(--color-text-primary)",
};

const CHROME: CSSProperties = { background: "var(--color-surface-raised)" };

const MAIN: CSSProperties = { gridArea: "main", position: "relative", minHeight: 0 };

const SCROLL: CSSProperties = { height: "100%", overflow: "auto" };

const OVERLAY: CSSProperties = { position: "absolute", inset: 0, pointerEvents: "none" };

export function AppShell(props: AppShellProps): JSX.Element {
  const { mainId, mainRef, connection, banner, canvasOverlay, children } = props;
  return (
    <div style={FRAME}>
      <SkipLink targetId={mainId} />
      <header style={{ ...CHROME, gridArea: "header" }}>
        <div data-shell-slot="connection">{connection}</div>
      </header>
      <nav aria-label="Primary" style={{ ...CHROME, gridArea: "nav" }} />
      <div data-shell-slot="banner" style={{ gridArea: "banner" }}>
        {banner}
      </div>
      <main id={mainId} ref={mainRef} tabIndex={-1} style={MAIN}>
        <div style={SCROLL}>{children}</div>
        <div data-shell-slot="canvas-overlay" style={OVERLAY}>
          {canvasOverlay}
        </div>
      </main>
      <aside style={{ ...CHROME, gridArea: "aside" }} />
      <footer style={{ ...CHROME, gridArea: "footer" }} />
    </div>
  );
}
