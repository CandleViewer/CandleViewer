// E14-T02 (#400, BQ-08): the port the engine binding implements. E14-T03 (#358) owns the engine's
// snapshot command; PR-B adapts this port to it. Snapshots keep API strings (`p` decimal string,
// `t` RFC 3339): conversion to ticks happens at the binding, never through float math here.
import type { DrawingStore } from "./drawingStore";
import type { LocalDrawing } from "./types";

export interface DrawingSink {
  publish(symbol: string, snapshot: readonly LocalDrawing[]): void;
}

/**
 * Publishes a pane's drawings now and again whenever the selection's reference changes (never per
 * unrelated store write). Returns the teardown.
 */
export function connectSink(
  store: DrawingStore,
  symbol: string,
  layoutId: string | null,
  sink: DrawingSink,
): () => void {
  let last = store.selectPane(symbol, layoutId);
  sink.publish(symbol, last);
  return store.subscribe(() => {
    const next = store.selectPane(symbol, layoutId);
    if (next === last) return;
    last = next;
    sink.publish(symbol, next);
  });
}

/** A recording sink for tests and stories. */
export interface FakeDrawingSink extends DrawingSink {
  readonly published: { readonly symbol: string; readonly snapshot: readonly LocalDrawing[] }[];
}

export function createFakeSink(): FakeDrawingSink {
  const published: FakeDrawingSink["published"] = [];
  return {
    published,
    publish(symbol, snapshot) {
      published.push({ symbol, snapshot });
    },
  };
}
