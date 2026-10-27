import type { JSX } from "react";
import { ScreenRoot } from "../features/app-shell/ScreenRoot";

/**
 * Placeholder route (E02-T04). Establishes the accessibility baseline
 * (landmark structure, visible focus, keyboard reachability) that the a11y
 * gate (Constitution §9 #9) runs against before E05/E10 add real screens.
 */
export function PlaceholderRoute(): JSX.Element {
  return (
    <ScreenRoot>
      <h1>CandleViewer</h1>
      <p>
        This is a placeholder route. The real route tree, RBAC guards and env badge ship in E10.
      </p>
      <a href="#placeholder-focus-target">Skip to focus target</a>
      <button id="placeholder-focus-target" type="button">
        Focusable placeholder control
      </button>
    </ScreenRoot>
  );
}
