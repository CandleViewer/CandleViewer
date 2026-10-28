import {
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
  type CSSProperties,
  type JSX,
} from "react";
import { probeLivenessNow } from "../../shell/bootstrap/liveness";
import { useShellSelector } from "../../shell/useShellSelector";
import {
  announce,
  clearAnnouncements,
  forget,
  lastWrittenAt,
  REGION_BUDGET_MS,
} from "../app-shell/announcer";
import { takeHandedBack } from "./bootOffline";
import { OFFLINE_COPY, SCR159_COPY, TAILNET_CHECKS } from "./copy";
import { OfflinePage } from "./OfflinePage";

const ENTERED = "offline:entered:";
const RECOVERED = "offline:recovered";
/** However often others speak, the entry gives way to them for this long in all, then speaks. */
const ENTRY_CAP_MS = 15_000;

/** Over the whole canvas; the overlay layer ignores the pointer, so the page takes it back. */
const PANE: CSSProperties = {
  position: "absolute",
  inset: 0,
  overflow: "auto",
  pointerEvents: "auto",
  background: "var(--color-surface-app)",
};

/**
 * SCR-159's in-canvas states (#306 slice 9; E10-D03 §9.2, board 10): the shell's canvas overlay
 * slot. While the liveness probe finds the backend unreachable with the browser offline or online
 * (tailnet_unreachable), the page covers the canvas and the chrome stays; the canvas is `inert`
 * underneath and never re-renders.
 *
 * The sequence: the page shows at once, silent. Its entry waits until the shell announcer's
 * assertive region has had REGION_BUDGET_MS since another writer's last message (E17-D02 §11), so
 * CMP-077's row 1 safety sentence is never cut: re-armed when someone else speaks during the wait,
 * each wait never longer than the budget (the wall clock can step back) and ENTRY_CAP_MS in all,
 * so a writer that keeps speaking cannot keep the page silent. Then the page's sentence is the
 * alert (the ticket's `role="alert"` once, through the shell announcer as CMP-077's) and focus
 * moves to the page's `h1`, which a screen reader reads as the heading: the page is spoken once
 * and announced before the focus moves (`05` §3.4 item 3). A later cause in the same episode says
 * heading and sentence, focus staying. On recovery focus returns to what had it before the page
 * when the page held it (`main` when that is gone, inert or another episode's), the alert is
 * cleared, and, once the socket is live, the recovery is said politely.
 * Not here: the cached read-only view with its age (none exists yet), the per-variant glyphs (not
 * in the icon registry; §9.2's template glyph instead).
 */
export function OfflineOverlay(): JSX.Element | null {
  const reachability = useShellSelector((s) => s.reachability);
  const live = useShellSelector((s) => s.connection.kind === "live");
  const { cause, probing, retryAtMs } = reachability;
  const shown = cause === "offline" || cause === "tailnet_unreachable";
  const pane = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const spoken = useRef(false); // this episode's page was said
  const ownWrite = useRef(Number.NaN); // when this overlay last wrote the assertive region
  const returnTo = useRef<HTMLElement | null>(null); // what had focus before the page
  const handedBack = useRef<boolean | null>(null); // R-902's hand-back, taken once per mount
  const [, tick] = useReducer((n: number) => n + 1, 0);

  useLayoutEffect(() => {
    const node = pane.current;
    const main = node?.closest("main") ?? null;
    const canvas = main?.querySelector(":scope > [data-shell-canvas]") ?? null;
    if (!shown || node === null || canvas === null) return undefined;
    const before = document.activeElement;
    if (before instanceof HTMLElement && before !== document.body && !node.contains(before)) {
      returnTo.current = before;
    }
    canvas.setAttribute("inert", "");
    return () => {
      canvas.removeAttribute("inert");
      if (node.isConnected) return; // StrictMode's rehearsal or an unmount: the page did not go
      const target = returnTo.current;
      returnTo.current = null; // this episode's, never the next one's
      const now = document.activeElement;
      if (now !== null && now !== document.body && now.isConnected) return; // the user moved on
      if (target?.isConnected && target.closest("[inert]") === null) target.focus();
      if (document.activeElement === document.body) main?.focus();
    };
  }, [shown]);

  useEffect(() => {
    if (cause !== "offline" && cause !== "tailnet_unreachable") return undefined;
    const enter = (): void => {
      const copy = OFFLINE_COPY[cause];
      const first = !spoken.current;
      spoken.current = true;
      if (first) forget(RECOVERED);
      const text = first ? copy.sentence : `${copy.heading}. ${copy.sentence}`;
      if (announce("assertive", text, ENTERED + cause))
        ownWrite.current = lastWrittenAt("assertive");
      if (!first) return;
      const now = document.activeElement;
      const page = pane.current;
      if (now instanceof HTMLElement && now !== document.body && !page?.contains(now)) {
        returnTo.current = now; // moved since the page showed: that is where focus goes back
      }
      heading.current?.focus();
    };
    let id: ReturnType<typeof setTimeout> | undefined;
    let waited = 0; // counted by the timers, so a wall-clock step cannot stretch the cap
    const attempt = (armedAt?: number): void => {
      const last = lastWrittenAt("assertive");
      if (last === armedAt) return enter(); // nobody spoke during the wait: the budget is spent
      const since = last === ownWrite.current ? -Infinity : last; // its own words it may follow
      const waitMs = Math.min(
        since + REGION_BUDGET_MS - Date.now(),
        REGION_BUDGET_MS,
        ENTRY_CAP_MS - waited,
      );
      if (waitMs <= 0) return enter();
      waited += waitMs;
      id = setTimeout(() => attempt(last), waitMs);
    };
    attempt();
    return () => clearTimeout(id);
  }, [cause]);

  // StrictMode's rehearsal (and an unmount) ends the episode as the alert's clearing does.
  useEffect(
    () => () => {
      spoken.current = false;
    },
    [],
  );

  useEffect(() => {
    if (!shown) return undefined;
    const id = setInterval(tick, 1000); // the countdown's clock: this page re-renders, nothing else
    return () => {
      clearInterval(id);
      clearAnnouncements(ENTERED); // recovery or unmount: no stale alert, and the next one is said
    };
  }, [shown]);

  useEffect(() => {
    handedBack.current ??= takeHandedBack(); // kept, so StrictMode's rehearsal does not lose it
    if (handedBack.current) spoken.current = true; // R-902's resume: said as a recovery, once live
  }, []);

  useEffect(() => {
    if (shown || !spoken.current || !live) return;
    spoken.current = false;
    announce("polite", SCR159_COPY.recovered, RECOVERED);
  }, [shown, live]);

  if (cause !== "offline" && cause !== "tailnet_unreachable") return null;
  const copy = OFFLINE_COPY[cause];
  const retryInS =
    probing || retryAtMs === null ? null : Math.max(1, Math.ceil((retryAtMs - Date.now()) / 1000));
  return (
    <div ref={pane} style={PANE}>
      <OfflinePage
        heading={copy.heading}
        sentence={copy.sentence}
        headingRef={heading}
        retryInS={retryInS}
        busy={probing}
        onRetry={probeLivenessNow}
        fallback
      >
        {cause === "tailnet_unreachable" ? (
          <ol style={{ margin: 0, paddingInlineStart: "var(--space-inset-lg)" }}>
            {TAILNET_CHECKS.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ol>
        ) : null}
      </OfflinePage>
    </div>
  );
}
