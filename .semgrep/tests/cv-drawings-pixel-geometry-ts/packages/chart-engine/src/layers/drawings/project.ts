// The engine projects chart space to pixels: it legitimately names them (E14-X03, #549).
declare const t: number;
declare const price: number;

export const screen = { x: t * 2, y: price * 3, px: 1 }; // ok: cv-drawings-pixel-geometry-ts
