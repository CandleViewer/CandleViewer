// Outside the store: a pointer is in pixels, and only the store persists (E14-X03, #549).
declare const e: { clientX: number; clientY: number };

export const hit = { x: e.clientX, y: e.clientY }; // ok: cv-drawings-pixel-geometry-ts
