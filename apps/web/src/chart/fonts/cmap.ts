// The decoded font's Unicode `cmap` coverage (E11-S11 F-03, BQ-265): which of the characters the
// engine needs map to no glyph. Formats 4 and 12 only, the ones the engine's own reader takes; any
// other or malformed table covers nothing, so a check against it fails closed.

/** The characters of `chars` (by code point) the sfnt's Unicode `cmap` does not map. */
export function missingGlyphs(sfnt: Uint8Array, chars: string): string[] {
  const v = new DataView(sfnt.buffer, sfnt.byteOffset, sfnt.byteLength);
  const subtables: number[] = [];
  try {
    let cmap = -1;
    for (let i = 0; i < v.getUint16(4); i += 1)
      if (v.getUint32(12 + i * 16) === 0x636d6170) cmap = v.getUint32(20 + i * 16);
    for (let i = 0; cmap >= 0 && i < v.getUint16(cmap + 2); i += 1) {
      const rec = cmap + 4 + i * 8;
      const [pid, eid] = [v.getUint16(rec), v.getUint16(rec + 2)];
      if (pid === 0 || (pid === 3 && (eid === 1 || eid === 10)))
        subtables.push(cmap + v.getUint32(rec + 4));
    }
  } catch {
    subtables.length = 0; // a truncated directory maps nothing
  }
  const mapped = (cp: number): boolean =>
    subtables.some((at) => {
      try {
        return glyphOf(v, at, cp) !== 0;
      } catch {
        return false; // a subtable that runs off the end maps nothing
      }
    });
  return [...new Set(chars)].filter((ch) => !mapped(ch.codePointAt(0) ?? 0));
}

function glyphOf(v: DataView, at: number, cp: number): number {
  const format = v.getUint16(at);
  if (format === 4) {
    const segX2 = v.getUint16(at + 6);
    for (let s = 0; s < segX2; s += 2) {
      const end = v.getUint16(at + 14 + s);
      if (end < cp) continue;
      const start = v.getUint16(at + 16 + segX2 + s);
      if (start > cp) return 0;
      const delta = v.getUint16(at + 16 + 2 * segX2 + s);
      const rangeAt = at + 16 + 3 * segX2 + s;
      const range = v.getUint16(rangeAt);
      if (range === 0) return (cp + delta) & 0xffff;
      const g = v.getUint16(rangeAt + range + 2 * (cp - start));
      return g === 0 ? 0 : (g + delta) & 0xffff;
    }
    return 0;
  }
  if (format === 12) {
    const groups = v.getUint32(at + 12);
    for (let i = 0; i < groups; i += 1) {
      const g = at + 16 + i * 12;
      const [start, end] = [v.getUint32(g), v.getUint32(g + 4)];
      if (cp >= start && cp <= end) return v.getUint32(g + 8) + (cp - start);
    }
  }
  return 0;
}
