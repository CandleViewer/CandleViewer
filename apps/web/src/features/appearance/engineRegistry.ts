import type { EngineHandle } from "@candleviewer/chart-engine";
import { readEngineTheme } from "./chartColorMode.js";

type ThemedEngine = Pick<EngineHandle, "setTheme">;

/** Live engine instances mounted by the chart host adapter (WebGL surfaces). */
const engines = new Set<ThemedEngine>();

/**
 * Root attributes whose change must repaint every canvas. High contrast is no attribute of its
 * own: the theme runtime reports it as `data-theme="high-contrast"`.
 */
const THEME_ATTRS = ["data-theme", "data-palette", "data-convention"];

let observer: MutationObserver | undefined;

function pushTheme(targets: Iterable<ThemedEngine>): void {
  const theme = readEngineTheme();
  for (const e of targets) e.setTheme(theme);
}

function ensureObserver(): void {
  if (observer !== undefined || typeof MutationObserver === "undefined") return;
  observer = new MutationObserver(() => pushTheme(engines));
  observer.observe(document.documentElement, { attributes: true, attributeFilter: THEME_ATTRS });
}

/**
 * Registers an engine. It receives the current theme immediately and again on
 * every theme / high-contrast / palette / convention switch, so no canvas is
 * left on stale colours (US-SET-005, AC1). The host adapter calls this on mount
 * and invokes the returned disposer on unmount.
 */
export function registerEngine(engine: ThemedEngine): () => void {
  engines.add(engine);
  ensureObserver();
  pushTheme([engine]);
  return () => {
    engines.delete(engine);
    if (engines.size === 0) {
      observer?.disconnect();
      observer = undefined;
    }
  };
}

export function registeredEngines(): readonly ThemedEngine[] {
  return [...engines];
}
