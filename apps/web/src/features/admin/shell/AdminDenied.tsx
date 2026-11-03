import { useEffect, useRef, type JSX } from "react";
import { ForbiddenState } from "@candleviewer/ui";
import { THEME_ANALYTICS_EVENT } from "../../../shell/bootstrap/themeStore";
import { announce } from "../../app-shell/announcer";
import { ScreenRoot } from "../../app-shell/ScreenRoot";
import { routerRenderLink } from "../routerLink";

/**
 * PROPOSED (owner E09-D09 §4.4, whose row 4 sets the voice, assertive and once, but no words for a
 * route the replacement takes; E42-D03 N-2 cites it): what the withdrawal says.
 */
export const WITHDRAWN_ANNOUNCEMENT = "Your access changed.";
/** Said once per page load: the area stays withdrawn until a reload, however often it is shown. */
const WITHDRAWN_KEY = "admin:withdrawn";

export interface AdminDeniedProps {
  /** The `403` problem's `instance`, CMP-089's Ref; none when the body carried none. */
  readonly refId: string | undefined;
}

/**
 * SCR-154 N-2 (E42-S01, BQ-8): an admin read answered `403` while the owner was here, so the area is
 * gone. CMP-089's withdrawn variant replaces the band and the page, with the way back to the
 * workspace and the Ref. It is no route change, so no route announcement: the shell's announcer
 * says "Your access changed." once, assertive (E09-D09 §4.4 row 4; A-5330-03), and then focus, if
 * the replaced page held it, moves to its `h1`, as the shell's route focus would.
 */
export function AdminDenied({ refId }: AdminDeniedProps): JSX.Element {
  const root = useRef<HTMLDivElement>(null);
  const reported = useRef(false);
  useEffect(() => {
    if (!reported.current) {
      reported.current = true;
      const detail = { name: "error.403_shown", variant: "withdrawn" };
      window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
    }
    announce("assertive", WITHDRAWN_ANNOUNCEMENT, WITHDRAWN_KEY);
    const active = document.activeElement;
    if (active === null || active === document.body || active.tagName === "MAIN") {
      root.current?.querySelector<HTMLElement>("h1")?.focus();
    }
  }, []);
  return (
    <div ref={root}>
      <ScreenRoot>
        <ForbiddenState
          variant="withdrawn"
          homeHref="/terminal"
          renderLink={routerRenderLink}
          {...(refId === undefined ? {} : { refId })}
        />
      </ScreenRoot>
    </div>
  );
}
