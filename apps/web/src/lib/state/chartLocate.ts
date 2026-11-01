// E22-S01 (#714) BQ-213: the app-level seam a tape row's click or `Enter` calls to put the charts'
// crosshair on a print (D4-08). The engine has no set-crosshair API and the app no sync bus yet
// (G-55), so this only publishes the request; the E11/E15 owner wires a chart to `subscribe`.
// `packages/chart-engine` is not touched.

export interface LocateRequest {
  readonly symbol: string;
  /** The print's `ts_ms`: epoch milliseconds, UTC. */
  readonly tsMs: number;
  readonly price: number;
}

export type LocateListener = (request: LocateRequest) => void;

const listeners = new Set<LocateListener>();

/** Asks every subscribed chart to locate the print; a no-op when none listens. */
export function locate(request: LocateRequest): void {
  if (!Number.isFinite(request.tsMs) || !Number.isFinite(request.price)) return;
  for (const listener of [...listeners]) listener(request);
}

export function subscribeLocate(listener: LocateListener): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}
