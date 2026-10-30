import {
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
  useState,
  type CSSProperties,
  type JSX,
} from "react";
import { keepSoftwareNow, retryGpuNow } from "../../shell/bootstrap/gpuCrash";
import { probeLivenessNow } from "../../shell/bootstrap/liveness";
import { getShellState } from "../../shell/bootstrap/store";
import type { GpuCrash } from "../../shell/ShellPort";
import { useShellSelector } from "../../shell/useShellSelector";
import {
  announce,
  clearAnnouncements,
  forget,
  lastWrittenAt,
  REGION_BUDGET_MS,
} from "../app-shell/announcer";
import { formatUtcClock } from "../app-shell/clock";
import { takeHandedBack } from "./bootOffline";
import { GPU_COPY, OFFLINE_COPY, SCR159_COPY, TAILNET_CHECKS } from "./copy";
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
const LIST: CSSProperties = { margin: 0, paddingInlineStart: "var(--space-inset-lg)" };

type Cause = "offline" | "tailnet_unreachable" | "gpu";

const gpuSentence = (crash: GpuCrash): string =>
  GPU_COPY.sentence(formatUtcClock(crash.crashedAtMs));

/** What a page says on entry; the GPU page's from the latest crash, `null` once it is answered. */
function entryCopy(cause: Cause): { heading: string; sentence: string } | null {
  if (cause !== "gpu") return OFFLINE_COPY[cause];
  const crash = getShellState().gpuCrash;
  return crash === null ? null : { heading: GPU_COPY.heading, sentence: gpuSentence(crash) };
}

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
 * In the desktop app a GPU-process crash shows the GPU page the same way (slice 9c), under the
 * server's pages when both hold, until it is answered: Retry now relaunches with the GPU, from a
 * click only; Keep software rendering hands the condition to SCR-153's GPU row for the session.
 * Only a server's page or R-902's resume has a recovery to say; the GPU page's end says nothing.
 * Not here: the cached read-only view with its age (none exists yet), the per-variant glyphs (not
 * in the icon registry; §9.2's template glyph instead).
 */
export function OfflineOverlay(): JSX.Element | null {
  const reachability = useShellSelector((s) => s.reachability);
  const live = useShellSelector((s) => s.connection.kind === "live");
  const crash = useShellSelector((s) => s.gpuCrash);
  const { probing, retryAtMs } = reachability;
  const net =
    reachability.cause === "offline" || reachability.cause === "tailnet_unreachable"
      ? reachability.cause
      : null;
  const cause: Cause | null = net ?? (crash === null ? null : "gpu"); // the server's page first
  const shown = cause !== null;
  const pane = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const spoken = useRef(false); // this episode's page was said
  const lost = useRef(false); // a server's page or R-902's resume: its recovery is said
  const ownWrite = useRef(Number.NaN); // when this overlay last wrote the assertive region
  const returnTo = useRef<HTMLElement | null>(null); // what had focus before the page
  const handedBack = useRef<boolean | null>(null); // R-902's hand-back, taken once per mount
  const [, tick] = useReducer((n: number) => n + 1, 0);
  const [retrying, setRetrying] = useState(false);

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
    if (cause === null) return undefined;
    const enter = (): void => {
      const copy = entryCopy(cause);
      if (copy === null) return; // the crash was answered meanwhile
      const first = !spoken.current;
      spoken.current = true;
      if (cause !== "gpu") {
        // a server outage that begins under a GPU page already said is an episode of its own
        if (!first && !lost.current) {
          forget(ENTERED + cause);
          forget(RECOVERED);
        }
        lost.current = true;
      }
      if (cause === "gpu" && !first) forget(ENTERED + cause); // back from a server page: said again
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
      lost.current = false;
    },
    [],
  );

  const ticking = net !== null;
  useEffect(() => {
    if (!ticking) return undefined;
    const id = setInterval(tick, 1000); // the countdown's clock: this page re-renders, nothing else
    return () => clearInterval(id);
  }, [ticking]);

  useEffect(() => {
    if (!shown) return undefined;
    return () => clearAnnouncements(ENTERED); // recovery or unmount: no stale alert, next one said
  }, [shown]);

  useEffect(() => {
    handedBack.current ??= takeHandedBack(); // kept, so StrictMode's rehearsal does not lose it
    if (handedBack.current) lost.current = true; // R-902's resume: said as a recovery, once live
  }, []);

  useEffect(() => {
    if (net === null && lost.current && live) {
      lost.current = false;
      announce("polite", SCR159_COPY.recovered, RECOVERED);
    }
    if (!shown && !lost.current) spoken.current = false; // the episode is over
  }, [net, shown, live]);

  const retryGpu = (): void => {
    setRetrying(true);
    // A refusal (no crash this session, or a retry in the last 60 s) says nothing new.
    void retryGpuNow()
      .catch(() => undefined)
      .finally(() => setRetrying(false));
  };

  if (net === null) {
    if (crash === null) return null;
    return (
      <div ref={pane} style={PANE}>
        <OfflinePage
          heading={GPU_COPY.heading}
          sentence={gpuSentence(crash)}
          headingRef={heading}
          retryInS={null}
          busy={retrying}
          onRetry={retryGpu}
          primary
          secondary={{ label: GPU_COPY.keep, onClick: keepSoftwareNow }}
        >
          <ul style={LIST}>
            {GPU_COPY.limits.map((limit) => (
              <li key={limit}>{limit}</li>
            ))}
          </ul>
          <p style={{ margin: 0 }}>{GPU_COPY.restarts(crash.restartCount)}</p>
        </OfflinePage>
      </div>
    );
  }
  const copy = OFFLINE_COPY[net];
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
        {net === "tailnet_unreachable" ? (
          <ol style={LIST}>
            {TAILNET_CHECKS.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ol>
        ) : null}
      </OfflinePage>
    </div>
  );
}
