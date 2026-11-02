// E22-S01 (#714) BQ-206 / BQ-215: the dev / Playwright harness mount. `main.tsx` loads it only in
// a build made with `VITE_FLAG_ORDERFLOW_TAPE=1` and only on `TAPE_HARNESS_PATH`, before the shell
// starts: no sign-in, no socket, no server. It renders SCR-053 at the 400 x 736 frame of D02 §2 for
// BTCUSDT, fed by the seeded in-page feeder (`?rate=2000&seed=577`), and exposes read-only counters
// for the perf spec on `window.__cvTapeHarness`. RULED BQ-206: no product UI mounts the panel; E15
// docks it, and that ticket removes this harness with the flag (C-4.13).
import { ThemeProvider } from "@candleviewer/ui";
import { StrictMode, type JSX } from "react";
import { createRoot } from "react-dom/client";
import { APP_THEME_OPTIONS } from "../../../shell/bootstrap/themeStore";
import { TapePanel } from "../view/TapePanel";
import type { TapeController } from "../view/tapeController";
import { createFeeder, type Feeder } from "./feeder";

export const TAPE_HARNESS_SYMBOL = "BTCUSDT";

export interface TapeHarnessProbe {
  /** Prints the feeder handed to the panel. */
  injected(): number;
  /** Prints the panel's ingest appended to its ring, and its ring's length (BQ-215). */
  appended(): number;
  ringLength(): number;
  /** The panel's own work per frame, p95 ms, and the worst ingest, ms. */
  workP95Ms(): number;
  maxIngestMs(): number;
  /** `[role="row"]` nodes in the panel (the header included). */
  rows(): number;
  /** The fallback ladder's rung now (BQ-218): 0 is full rate, 2 writes rows every 2nd frame. */
  rung(): number;
}

declare global {
  interface Window {
    __cvTapeHarness?: TapeHarnessProbe;
  }
}

const param = (name: string, fallback: number, max: number): number => {
  const raw = Number(new URLSearchParams(window.location.search).get(name));
  return Number.isFinite(raw) && raw > 0 && raw <= max ? Math.floor(raw) : fallback;
};

/** Mounts the harness into `container`; the returned function unmounts it (tests). */
export function mountTapeHarness(container: HTMLElement): () => void {
  const rate = param("rate", 2_000, 20_000);
  const seed = param("seed", 577, 2 ** 31);
  const feeder = createFeeder({
    symbol: TAPE_HARNESS_SYMBOL,
    rate,
    seed,
    now: () => performance.now(),
    startTsMs: Date.UTC(2026, 9, 31, 14, 2, 11),
  });
  let controller: TapeController | null = null;
  window.__cvTapeHarness = {
    injected: feeder.injected,
    appended: () => controller?.metrics().appended ?? 0,
    ringLength: () => controller?.metrics().ringLength ?? 0,
    workP95Ms: () => controller?.metrics().workP95Ms ?? 0,
    maxIngestMs: () => controller?.metrics().maxIngestMs ?? 0,
    rows: () => container.querySelectorAll('[role="row"]').length,
    rung: () => controller?.metrics().rung ?? 0,
  };
  const root = createRoot(container);
  root.render(
    <StrictMode>
      {/* the app's one theme store, as App.tsx mounts it: without the root `data-theme` the
          tokens resolve to nothing and the panel lays out in the UA's default serif (BQ-215) */}
      <ThemeProvider options={APP_THEME_OPTIONS}>
        <Harness
          client={feeder.client}
          onController={(c) => {
            controller = c;
          }}
        />
      </ThemeProvider>
    </StrictMode>,
  );
  return () => {
    root.unmount();
    delete window.__cvTapeHarness;
  };
}

interface HarnessProps {
  readonly client: Feeder["client"];
  readonly onController: (controller: TapeController | null) => void;
}

function Harness({ client, onController }: HarnessProps): JSX.Element {
  return (
    <main style={{ height: "100vh", display: "flex", background: "var(--color-surface-app)" }}>
      <h1 className="cv-visually-hidden">Tape harness</h1>
      <div style={{ width: "400px", height: "736px", marginInlineStart: "auto" }}>
        <TapePanel
          symbol={TAPE_HARNESS_SYMBOL}
          enabled
          client={client}
          transport="connected"
          fetchTrades={() => Promise.resolve([])}
          registerKeys={false}
          onController={onController}
        />
      </div>
    </main>
  );
}
