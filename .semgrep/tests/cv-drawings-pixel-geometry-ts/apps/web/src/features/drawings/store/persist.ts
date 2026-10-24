// Fixtures for cv-drawings-pixel-geometry-ts: a persisted drawing is chart space, a time `t` and a price `p` (E14-X03, #549).
declare function post(body: unknown): void;
declare const t: number;
declare const x: number;
declare const y: number;
declare const px: number;
declare const evt: { x: number; y: number };
declare const point: { t: number; p: string };

export function persist(): void {
  post({ geometry: { points: [{ x, y }] } }); // ruleid: cv-drawings-pixel-geometry-ts
  post({ geometry: { points: [{ t, p: "1", px }] } }); // ruleid: cv-drawings-pixel-geometry-ts
  // prettier-ignore
  post({ points: [{ "x": 1 }] }); // ruleid: cv-drawings-pixel-geometry-ts
  post({ ...point, y: 2 }); // ruleid: cv-drawings-pixel-geometry-ts
  post([{ t, p: "1", px: 3 }]); // ruleid: cv-drawings-pixel-geometry-ts
}
export const toInput = () => ({ t, p: "1", y: 2 }); // ruleid: cv-drawings-pixel-geometry-ts
export function move(anchor: Record<string, unknown>): void {
  anchor.x = 3; // ruleid: cv-drawings-pixel-geometry-ts
  anchor["px"] = 4; // ruleid: cv-drawings-pixel-geometry-ts
}

// Where a naive "the names x, y or px" rule would misfire:
export function chartSpace(): void {
  post({ op: "create", drawing: { geometry: { points: [{ t, p: "61200.10" }] } } }); // ok: cv-drawings-pixel-geometry-ts
  post({ max: 1, pxTotal: 2, xs: [x], index: y + px }); // ok: cv-drawings-pixel-geometry-ts
  post([evt.x + evt.y, point.t]); // ok: cv-drawings-pixel-geometry-ts
  (point as { p: string }).p = "2"; // ok: cv-drawings-pixel-geometry-ts
}
