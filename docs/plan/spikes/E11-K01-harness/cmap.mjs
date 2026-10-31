// THROWAWAY SPIKE HARNESS (E11-K01, Sc2). Minimal sfnt `cmap` reader (formats 4 and 12) so coverage is
// decided from the font file itself, never from what Chromium's fallback happens to draw. TTF, OTF, TTC
// (face 0) or WOFF2, so the shipped `packages/ui/src/fonts/*.woff2` files (16 §2.2) are read as they ship.
import { brotliDecompressSync } from "node:zlib";

const tag = (buf, o) => String.fromCharCode(...buf.subarray(o, o + 4));

// WOFF2 (W3C WOFF 2.0 §4–§5): cmap and name are never transformed, so the decompressed stream holds them
// verbatim. Returns { cmap, name } as byte views; glyf/loca/hmtx are skipped, not reconstructed.
function woff2Tables(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  if (tag(buf, 4) === "ttcf") throw new Error("WOFF2 collections are not supported");
  const numTables = dv.getUint16(12);
  let o = 48;
  const base128 = () => {
    let v = 0;
    for (let i = 0; i < 5; i += 1) {
      const b = buf[o++];
      v = v * 128 + (b & 0x7f);
      if (!(b & 0x80)) return v;
    }
    throw new Error("bad UIntBase128");
  };
  const want = { 0: "cmap", 5: "name" };
  const dir = [];
  for (let i = 0; i < numTables; i += 1) {
    const flags = buf[o++];
    const idx = flags & 0x3f;
    const t = idx === 63 ? tag(buf, (o += 4) - 4) : want[idx];
    const ver = (flags >> 6) & 3;
    const orig = base128();
    const transformed = idx === 10 || idx === 11 ? ver !== 3 : ver !== 0;
    dir.push({ t, len: transformed ? base128() : orig });
  }
  const stream = brotliDecompressSync(buf.subarray(o, o + dv.getUint32(20)));
  const out = {};
  let at = 0;
  for (const d of dir) {
    if (d.t === "cmap" || d.t === "name") out[d.t] = stream.subarray(at, at + d.len);
    at += d.len;
  }
  return out;
}

// The `cmap` and `name` tables of any supported container, as byte views.
function tables(buf) {
  if (tag(buf, 0) === "wOF2") return woff2Tables(buf);
  if (tag(buf, 0) === "wOFF")
    throw new Error("WOFF 1 is not supported; pass WOFF2, TTF, OTF or TTC");
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const base = tag(buf, 0) === "ttcf" ? dv.getUint32(12) : 0; // a .ttc: face 0
  const out = {};
  for (let i = 0; i < dv.getUint16(base + 4); i += 1) {
    const r = base + 12 + i * 16;
    const t = tag(buf, r);
    if (t === "cmap" || t === "name")
      out[t] = buf.subarray(dv.getUint32(r + 8), dv.getUint32(r + 8) + dv.getUint32(r + 12));
  }
  return out;
}

// The font's version string (name ID 5), so a rerun can show the TTF and the shipped WOFF2 are one version.
export function fontVersion(buf) {
  const n = tables(buf).name;
  if (!n) return null;
  const dv = new DataView(n.buffer, n.byteOffset, n.byteLength);
  const strings = dv.getUint16(4);
  for (let i = 0; i < dv.getUint16(2); i += 1) {
    const r = 6 + i * 12;
    if (dv.getUint16(r + 6) !== 5) continue;
    const [pid, len, off] = [dv.getUint16(r), dv.getUint16(r + 8), dv.getUint16(r + 10)];
    const raw = n.subarray(strings + off, strings + off + len);
    if (pid === 1) return String.fromCharCode(...raw);
    let s = "";
    for (let k = 0; k + 1 < raw.length; k += 2)
      s += String.fromCharCode((raw[k] << 8) | raw[k + 1]);
    return s;
  }
  return null;
}

export function fontHas(buf, codepoints) {
  const t = tables(buf).cmap;
  if (!t) throw new Error("no cmap table");
  const dv = new DataView(t.buffer, t.byteOffset, t.byteLength);
  const cmap = 0;
  const subs = [];
  for (let i = 0; i < dv.getUint16(cmap + 2); i += 1) {
    const r = cmap + 4 + i * 8;
    const [pid, eid] = [dv.getUint16(r), dv.getUint16(r + 2)];
    if (pid === 0 || (pid === 3 && (eid === 1 || eid === 10)))
      subs.push(cmap + dv.getUint32(r + 4));
  }
  const glyphOf = (cp) => {
    for (const s of subs) {
      const fmt = dv.getUint16(s);
      if (fmt === 12) {
        for (let g = 0, n = dv.getUint32(s + 12); g < n; g += 1) {
          const o = s + 16 + g * 12;
          if (cp >= dv.getUint32(o) && cp <= dv.getUint32(o + 4))
            return dv.getUint32(o + 8) + cp - dv.getUint32(o);
        }
      } else if (fmt === 4 && cp <= 0xffff) {
        const seg = dv.getUint16(s + 6) / 2;
        const [ends, starts, deltas, ranges] = [14, 16 + seg * 2, 16 + seg * 4, 16 + seg * 6].map(
          (o) => s + o,
        );
        for (let k = 0; k < seg; k += 1) {
          if (cp > dv.getUint16(ends + k * 2)) continue;
          const start = dv.getUint16(starts + k * 2);
          if (cp < start) break;
          const delta = dv.getUint16(deltas + k * 2);
          const ro = dv.getUint16(ranges + k * 2);
          if (ro === 0) return (cp + delta) & 0xffff;
          const g = dv.getUint16(ranges + k * 2 + ro + (cp - start) * 2);
          return g === 0 ? 0 : (g + delta) & 0xffff;
        }
      }
    }
    return 0;
  };
  return new Map([...codepoints].map((ch) => [ch, glyphOf(ch.codePointAt(0)) !== 0]));
}
