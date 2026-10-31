import { useEffect, useRef, useState, type JSX, type RefObject } from "react";

/** SCR-018: optional 8-stop tour. Dismissible, resumable, never auto-shown twice. */
export const TOUR_STOPS: readonly { readonly title: string; readonly body: string }[] = [
  { title: "Chart", body: "The main candlestick chart for the selected symbol." },
  { title: "Footprint", body: "Bid/ask volume per price level inside each candle." },
  { title: "DOM", body: "Live depth of market ladder." },
  { title: "Order ticket", body: "Place orders; every entry carries a native stop-loss." },
  { title: "Positions", body: "Open positions and their protection state." },
  { title: "Rules", body: "Automations that watch the market for you." },
  { title: "Journal", body: "Review and annotate your trades." },
  { title: "Panic buttons", body: "Flatten or kill-switch controls. Never blocked by this tour." },
];
export const TOUR_SEEN_KEY = "cv.onboarding.tour.seen";

export function tourAlreadySeen(): boolean {
  try {
    return window.localStorage.getItem(TOUR_SEEN_KEY) === "1";
  } catch {
    return true; // storage unavailable: never nag
  }
}
function markSeen(): void {
  try {
    window.localStorage.setItem(TOUR_SEEN_KEY, "1");
  } catch {
    /* ignore */
  }
}

export interface CoachMarkTourProps {
  readonly onClose: () => void;
  /**
   * Where focus goes on close when no element opened the tour (it auto-opened, so focus was on `body`) or the opener
   * is gone: the host's "Take the tour" control (D-04 / A11Y-F-0027, pattern A11Y-P-01).
   */
  readonly returnFocusTo?: RefObject<HTMLElement | null>;
}

export function CoachMarkTour({ onClose, returnFocusTo }: CoachMarkTourProps): JSX.Element {
  const [i, setI] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(document.activeElement);
  const fallback = useRef(returnFocusTo);
  fallback.current = returnFocusTo;
  const stop = TOUR_STOPS[i] ?? TOUR_STOPS[0]!;
  const last = i === TOUR_STOPS.length - 1;
  const close = (): void => {
    markSeen();
    onClose();
  };
  useEffect(() => {
    ref.current?.focus();
    const el = opener.current;
    return () => {
      const real = el instanceof HTMLElement && el !== document.body && el.isConnected;
      (real ? el : fallback.current?.current)?.focus();
    };
  }, []);
  useEffect(() => {
    markSeen();
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        markSeen();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={`Tour stop ${i + 1} of ${TOUR_STOPS.length}: ${stop.title}`}
      tabIndex={-1}
    >
      <h3>{stop.title}</h3>
      <p>{stop.body}</p>
      <progress value={i + 1} max={TOUR_STOPS.length} aria-label="Tour progress" />
      <button type="button" disabled={i === 0} onClick={() => setI(i - 1)}>
        Previous
      </button>
      <button type="button" onClick={() => (last ? close() : setI(i + 1))}>
        {last ? "Finish" : "Next"}
      </button>
      <button type="button" onClick={close}>
        Exit tour
      </button>
    </div>
  );
}
