import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  type CSSProperties,
  type JSX,
} from "react";
import { useNavigate } from "react-router";
import { Icon } from "@candleviewer/ui";
import { CLIENT_VERSION } from "../../lib/ws/protocol/frames";
import { backoffDelayWithJitter } from "../../shell/bootstrap/backoff";
import { runBootstrap } from "../../shell/bootstrap/bootstrap";
import { markReachable } from "../../shell/bootstrap/liveness";
import { getShellState } from "../../shell/bootstrap/store";
import { readString } from "../../shell/crash/redact";
import { reportCrash } from "../../shell/crash/reportCrash";
import { ScreenRoot } from "../app-shell/ScreenRoot";
import { bootDiverted, isUnreachableBoot, resumeBoot } from "./bootOffline";
import { BOOT_CHECKS, CHECK_GLYPHS, OFFLINE_COPY, SCR159_COPY } from "./copy";
import { OfflinePage } from "./OfflinePage";

type Check = keyof typeof CHECK_GLYPHS;
const GLYPH = { passed: "check", failed: "close", unknown: "minus" } as const;

/** R-902 is its own frame, outside the shell that paints `color.surface.app` (#4927's a11y gate). */
const PAGE: CSSProperties = {
  position: "fixed",
  inset: 0,
  overflowY: "auto",
  background: "var(--color-surface-app)",
  color: "var(--color-text-primary)",
};

const MARK: CSSProperties = {
  margin: 0,
  padding: "var(--space-inset-lg) var(--space-inset-lg) 0",
  color: "var(--color-text-primary)",
  fontWeight: "var(--font-weight-semibold)",
};
const LIST: CSSProperties = {
  display: "grid",
  gap: "var(--space-stack-xs)",
  margin: 0,
  padding: 0,
};
const ROW: CSSProperties = { display: "flex", alignItems: "center", gap: "var(--space-2)" };
const FOOT: CSSProperties = {
  margin: 0,
  padding: "0 var(--space-inset-lg) var(--space-inset-lg)",
  color: "var(--color-text-tertiary)",
  fontFamily: "var(--font-family-mono)",
};

/** The crash log's word for a thrown value: an Error's name (its class), else its type. */
const errorClass = (error: unknown): string =>
  readString(() => (error instanceof Error ? error.name : undefined)) ?? typeof error;

const row = (check: Check, text: string): JSX.Element => (
  <li key={text} style={ROW}>
    <Icon name={GLYPH[check]} decorative={false} label={CHECK_GLYPHS[check]} />
    {text}
  </li>
);

/**
 * R-902 `/offline` (#306 slice 9): SCR-159 backend-unreachable at boot, the full-screen takeover
 * (E10-D03 §9.2, E10-D02 f27). Nothing came from the server, so a public route: no chrome, no
 * user, no ENV badge (the environment is not known). The wordmark, §9.2's template with D02 f27's
 * checklist, and the client's own version. A diverted boot retries by itself on the 23 §9.2 table
 * ("Retrying in ~N s", its 1 Hz clock running only then); Retry now tries at once; while a try
 * runs the page is busy and has no countdown. Once the server answers (anything but
 * `isUnreachableBoot`), the liveness probe is told (`markReachable`) and start-up resumes at the
 * page asked for; the shell then says the recovery once, politely, when its socket is live. The
 * heading takes focus once. Not here: Copy details (a redacted payload and a clipboard egress,
 * SR-177, for a slice of their own) and "Tailnet connected", which no client signal can tell.
 */
export function BackendUnreachable(): JSX.Element {
  const copy = OFFLINE_COPY.backend_unreachable;
  const navigate = useNavigate();
  const heading = useRef<HTMLHeadingElement>(null);
  const busy = useRef(false); // a try is running: the re-entry guard, read before any render
  const mounted = useRef(true);
  const [diverted] = useState(bootDiverted); // decided once per mount
  const [trying, setTrying] = useState(false);
  const [round, setRound] = useState(0); // the automatic tries so far
  const [nextAtMs, setNextAtMs] = useState<number | null>(null);
  const [, tick] = useReducer((n: number) => n + 1, 0);

  const tryNow = useCallback(async (): Promise<void> => {
    if (busy.current) return;
    busy.current = true;
    setTrying(true);
    let answered = false;
    try {
      await runBootstrap();
      answered = !isUnreachableBoot(getShellState().bootstrap);
    } catch (error) {
      // `runBootstrap` is not meant to throw; if it does, the try failed and the loop goes on, and
      // the crash log keeps the error's class, never its message
      reportCrash(`R-902: a try threw ${errorClass(error)}`, "route", "R-902");
    } finally {
      busy.current = false;
      if (mounted.current) setTrying(false);
    }
    if (!mounted.current) return;
    if (!answered) {
      setRound((n) => n + 1);
      return;
    }
    markReachable(); // the server answered: the probe's verdict goes with the takeover
    const ready = getShellState().bootstrap.kind === "ready";
    navigate(resumeBoot(ready), { replace: true });
  }, [navigate]);

  useEffect(() => {
    if (!diverted) return undefined;
    const delayMs = backoffDelayWithJitter(round + 1);
    setNextAtMs(Date.now() + delayMs);
    const id = setTimeout(() => void tryNow(), delayMs);
    return () => clearTimeout(id);
  }, [diverted, round, tryNow]);

  useEffect(() => {
    mounted.current = true;
    heading.current?.focus();
    return () => {
      mounted.current = false;
    };
  }, []);

  const counting = !trying && nextAtMs !== null;
  useEffect(() => {
    if (!counting) return undefined;
    const id = setInterval(tick, 1000); // the countdown's clock, never announced
    return () => clearInterval(id);
  }, [counting]);

  const retryInS = counting ? Math.max(1, Math.ceil((nextAtMs - Date.now()) / 1000)) : null;
  return (
    <ScreenRoot style={PAGE}>
      <p style={MARK}>{SCR159_COPY.wordmark}</p>
      <OfflinePage
        heading={copy.heading}
        sentence={copy.sentence}
        headingRef={heading}
        retryInS={retryInS}
        busy={trying}
        onRetry={() => void tryNow()}
        primary
      >
        <ul style={LIST}>
          {row(navigator.onLine ? "passed" : "failed", BOOT_CHECKS.network)}
          {row("failed", BOOT_CHECKS.backend)}
          {row("unknown", BOOT_CHECKS.version)}
        </ul>
      </OfflinePage>
      <p style={FOOT}>{SCR159_COPY.buildLine(CLIENT_VERSION)}</p>
    </ScreenRoot>
  );
}
