import { useLayoutEffect, type CSSProperties, type JSX, type ReactNode, type Ref } from "react";
import { SKIP_LINK_COPY, SkipLink } from "@candleviewer/ui";
import { REFLOW_QUERY } from "./reflow";

/**
 * CMP-070 AppShell frame (E10-S01 S1, #304): props only, no router or store. It lives in apps/web
 * until the shell's presentational parts move to `packages/ui` (#304 plan §2).
 *
 * DOM order is the focus order of E10-D02 :254 (SkipLink → TopBar → NavRail → banner slot →
 * WorkspaceCanvas → RightRail → StatusBar); the grid places the banner row full width under the
 * top bar (E10-D03 §2). Landmarks per D02 :255: `banner`, `navigation` "Primary", `main`,
 * `complementary`, `contentinfo`. The top bar, right rail and status bar are empty placeholders
 * until slices S2–S6 fill them; `nav` takes the S5 rail. Under a CMP-043 modal the header, the
 * banner slot and the footer stay live, outside the inert page (`data-cv-inert-exempt`, E05-D02
 * H23; E10-D03 §1.2: the badges are never under a modal, above the reflow breakpoint), and the
 * scrim covers `main`'s band only (`useScrimInsets`); at the breakpoint a dialog fills the viewport
 * (§11.3).
 */
export interface AppShellProps {
  /** id of the one `main`, the skip link's target. */
  readonly mainId: string;
  readonly mainRef?: Ref<HTMLElement>;
  /** The CMP-071 rail, inside the `nav` "Primary" landmark. */
  readonly nav?: ReactNode;
  readonly connection?: ReactNode;
  /** CMP-072 (S2): renders the header row around the connection slot; absent, the bare slot. */
  readonly topBar?: (connection: JSX.Element) => ReactNode;
  /**
   * The CMP-211 Safety cluster (`ShellPanicSlot`), last in the header: the TopBar's right
   * (E10-D02 ruling 1). No wrapper node, so an empty slot adds nothing to the DOM or the Tab order.
   */
  readonly panic?: ReactNode;
  readonly banner?: ReactNode;
  readonly canvasOverlay?: ReactNode;
  /** The CMP-209 right rail (S6), inside the `complementary` landmark named `rightRailLabel`. */
  readonly rightRail?: ReactNode;
  readonly rightRailLabel?: string;
  /** The CMP-208 status bar, inside the `contentinfo` landmark. */
  readonly status?: ReactNode;
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

/** CMP-043's reflow breakpoint (`dialog.css`): 200 % zoom on the 1280 x 800 frame. */
const SCRIM_REFLOW = REFLOW_QUERY;

/**
 * The scrim's band, the shell's for every modal layer (E05-D02 H23; `dialog.css` and `drawer.css`
 * read it): `main`'s rows, so the TopBar and the StatusBar are never scrimmed (E10-D03 §1.2, §9.1).
 * At CMP-043's reflow breakpoint `main` is too short for a card (144 px at 200 %): no band, and a
 * dialog fills the viewport (§11.3: "every dialog fills the viewport, its footer stays one sticky
 * row and its body scrolls"). Re-measured as `main` or the viewport resizes (a zoom included).
 */
function useScrimInsets(mainId: string): void {
  useLayoutEffect(() => {
    const main = document.getElementById(mainId);
    if (main === null) return undefined;
    const root = document.documentElement.style;
    const reflow = typeof window.matchMedia === "function" ? window.matchMedia(SCRIM_REFLOW) : null;
    const clear = (): void => {
      root.removeProperty("--cv-scrim-inset-top");
      root.removeProperty("--cv-scrim-inset-bottom");
    };
    const place = (): void => {
      if (reflow?.matches === true) {
        clear();
        return;
      }
      const { top, bottom } = main.getBoundingClientRect();
      root.setProperty("--cv-scrim-inset-top", `${top}px`);
      root.setProperty("--cv-scrim-inset-bottom", `${window.innerHeight - bottom}px`);
    };
    place();
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    resize?.observe(main);
    window.addEventListener("resize", place);
    return () => {
      resize?.disconnect();
      window.removeEventListener("resize", place);
      clear();
    };
  }, [mainId]);
}

export function AppShell(props: AppShellProps): JSX.Element {
  const { mainId, mainRef, nav, connection, panic, banner, canvasOverlay, status, children } =
    props;
  const { rightRail, rightRailLabel } = props;
  useScrimInsets(mainId);
  return (
    <div style={FRAME}>
      <SkipLink targets={[{ id: mainId, label: SKIP_LINK_COPY.main }]} />
      <header data-cv-inert-exempt="" style={{ ...CHROME, gridArea: "header" }}>
        {(props.topBar ?? ((slot) => slot))(<div data-shell-slot="connection">{connection}</div>)}
        {panic}
      </header>
      <nav aria-label="Primary" style={{ ...CHROME, gridArea: "nav" }}>
        {nav}
      </nav>
      <div data-shell-slot="banner" data-cv-inert-exempt="" style={{ gridArea: "banner" }}>
        {banner}
      </div>
      <main id={mainId} ref={mainRef} tabIndex={-1} style={MAIN}>
        <div data-shell-canvas="" style={SCROLL}>
          {children}
        </div>
        <div data-shell-slot="canvas-overlay" style={OVERLAY}>
          {canvasOverlay}
        </div>
      </main>
      <aside aria-label={rightRailLabel} style={{ ...CHROME, gridArea: "aside" }}>
        {rightRail}
      </aside>
      <footer data-cv-inert-exempt="" style={{ ...CHROME, gridArea: "footer" }}>
        {status}
      </footer>
    </div>
  );
}
