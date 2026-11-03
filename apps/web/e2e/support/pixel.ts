import { inflateSync } from "node:zlib";

/**
 * The first pixel of a screenshot (a PNG, 8 bits per channel, RGB or RGBA) as `[r, g, b]`: the first
 * scanline's first pixel, which no PNG filter changes (every predictor reads 0 at the corner). A
 * one-pixel `clip` reads the colour painted at one point, where `elementFromPoint` cannot answer
 * (an `inert` canvas under an overlay still paints).
 */
export function firstPixel(png: Buffer): readonly [number, number, number] {
  let at = 8; // past the signature
  let depth = 0;
  let colour = -1;
  const data: Buffer[] = [];
  while (at + 8 <= png.length) {
    const length = png.readUInt32BE(at);
    const type = png.toString("ascii", at + 4, at + 8);
    const body = png.subarray(at + 8, at + 8 + length);
    if (type === "IHDR") {
      depth = body[8] ?? 0;
      colour = body[9] ?? -1;
    } else if (type === "IDAT") {
      data.push(body);
    } else if (type === "IEND") {
      break;
    }
    at += 12 + length;
  }
  if (depth !== 8 || (colour !== 2 && colour !== 6)) {
    throw new Error(`firstPixel: an 8-bit RGB or RGBA PNG only (depth ${depth}, colour ${colour})`);
  }
  const raw = inflateSync(Buffer.concat(data));
  // raw[0] is the first scanline's filter type; its first pixel's channels follow.
  return [raw[1] ?? 0, raw[2] ?? 0, raw[3] ?? 0];
}

/** `rgb(r, g, b)` or `rgba(r, g, b, a)` as `[r, g, b]`. */
export function rgbOf(css: string): readonly [number, number, number] {
  const [r = Number.NaN, g = Number.NaN, b = Number.NaN] = (css.match(/\d+(\.\d+)?/g) ?? []).map(
    Number,
  );
  return [r, g, b];
}
