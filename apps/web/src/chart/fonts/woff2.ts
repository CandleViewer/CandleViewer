// WOFF2 → sfnt for the chart's text host adapter (E11-S11 PR C): the container, the table
// stream and the `glyf`/`loca` transform of W3C WOFF2 §5, rebuilt into a TrueType file the engine's
// `FontFace` and `cmap` reader take. Brotli is injected (the app's lazy `brotli` chunk), so this file
// stays pure. Every read is bounds-checked: a malformed file is a `Woff2Error`, never a guess.

/** Brotli decompression of exactly `outSize` bytes. */
export type BrotliDecode = (input: Uint8Array, outSize: number) => Uint8Array;

export class Woff2Error extends Error {
  override readonly name = "Woff2Error";
}

/** The decoded font may not exceed the engine's per-face bound (`init.fonts`, 8 MiB). */
export const MAX_SFNT_BYTES = 8 * 1024 * 1024;

/** WOFF2 §4.3's known-table tags, by the 6-bit index of a directory entry's flags. */
const KNOWN = (
  "cmap,head,hhea,hmtx,maxp,name,OS/2,post,cvt ,fpgm,glyf,loca,prep,CFF ,VORG,EBDT,EBLC,gasp,hdmx," +
  "kern,LTSH,PCLT,VDMX,vhea,vmtx,BASE,GDEF,GPOS,GSUB,EBSC,JSTF,MATH,CBDT,CBLC,COLR,CPAL,SVG ,sbix," +
  "acnt,avar,bdat,bloc,bsln,cvar,fdsc,feat,fmtx,fvar,gvar,hsty,just,lcar,mort,morx,opbd,prop,trak," +
  "Zapf,Silf,Glat,Gloc,Feat,Sill"
).split(",");

class Reader {
  private readonly v: DataView;
  constructor(
    readonly b: Uint8Array,
    public p = 0,
  ) {
    this.v = new DataView(b.buffer, b.byteOffset, b.byteLength);
  }
  private need(n: number): number {
    const at = this.p;
    if (at + n > this.b.length) throw new Woff2Error("WOFF2 data is truncated");
    this.p += n;
    return at;
  }
  u8 = (): number => this.v.getUint8(this.need(1));
  u16 = (): number => this.v.getUint16(this.need(2));
  i16 = (): number => this.v.getInt16(this.need(2));
  u32 = (): number => this.v.getUint32(this.need(4));
  bytes = (n: number): Uint8Array => this.b.subarray(this.need(n), this.p);
  base128(): number {
    let acc = 0;
    for (let i = 0; i < 5; i += 1) {
      const c = this.u8();
      if (i === 0 && c === 0x80) throw new Woff2Error("UIntBase128 has a leading zero");
      if (acc > 0x1ffffff) throw new Woff2Error("UIntBase128 overflows");
      acc = acc * 128 + (c & 0x7f);
      if ((c & 0x80) === 0) return acc;
    }
    throw new Woff2Error("UIntBase128 is longer than 5 bytes");
  }
  u255(): number {
    const c = this.u8();
    if (c === 253) return this.u16();
    if (c === 255) return 253 + this.u8();
    if (c === 254) return 506 + this.u8();
    return c;
  }
}

/** A growable byte buffer, bounded by `MAX_SFNT_BYTES`. */
class Writer {
  n = 0;
  private b: Uint8Array;
  constructor(initial: number) {
    this.b = new Uint8Array(Math.max(16, initial));
  }
  bytes(src: ArrayLike<number>): void {
    if (this.n + src.length > this.b.length) {
      if (this.n + src.length > MAX_SFNT_BYTES) throw new Woff2Error("glyf exceeds the size bound");
      const next = new Uint8Array(Math.min(MAX_SFNT_BYTES, 2 * (this.n + src.length)));
      next.set(this.b.subarray(0, this.n));
      this.b = next;
    }
    this.b.set(src, this.n);
    this.n += src.length;
  }
  u16(v: number): void {
    this.bytes([(v >> 8) & 0xff, v & 0xff]);
  }
  done(): Uint8Array {
    return this.b.slice(0, this.n);
  }
}

interface Entry {
  readonly tag: string;
  readonly version: number;
  readonly origLength: number;
  readonly length: number; // in the decompressed stream
}

/** Decodes a WOFF2 font (single face, TrueType outlines) to sfnt bytes. */
export function decodeWoff2(woff2: Uint8Array, brotli: BrotliDecode): Uint8Array<ArrayBuffer> {
  const r = new Reader(woff2);
  if (r.u32() !== 0x774f4632) throw new Woff2Error("not a WOFF2 file");
  const flavor = r.u32();
  if (flavor === 0x74746366) throw new Woff2Error("WOFF2 collections are not supported");
  if (r.u32() !== woff2.length) throw new Woff2Error("WOFF2 length field disagrees with the file");
  const numTables = r.u16();
  r.p = 20;
  const compressed = r.u32();
  r.p = 48;
  const entries: Entry[] = [];
  for (let i = 0; i < numTables; i += 1) {
    const flags = r.u8();
    const tag =
      (flags & 63) === 63 ? String.fromCharCode(...r.bytes(4)) : (KNOWN[flags & 63] ?? "");
    const version = flags >> 6;
    const origLength = r.base128();
    const glyfLoca = tag === "glyf" || tag === "loca";
    // §5.1: for glyf/loca, 0 is the transform and 3 the null transform; 1 and 2 are reserved.
    if (glyfLoca && version !== 0 && version !== 3)
      throw new Woff2Error(`reserved ${tag} transform version ${version}`);
    const transformed = glyfLoca ? version !== 3 : version !== 0;
    if (transformed && !glyfLoca) throw new Woff2Error(`unsupported ${tag} transform`);
    const length = transformed ? r.base128() : origLength;
    entries.push({ tag, version, origLength, length });
  }
  const total = entries.reduce((s, e) => s + e.length, 0);
  if (total > MAX_SFNT_BYTES) throw new Woff2Error("WOFF2 table data exceeds the size bound");
  const stream = brotli(r.bytes(compressed), total);
  if (stream.length !== total) throw new Woff2Error("WOFF2 table stream has the wrong size");

  const tables = new Map<string, Uint8Array>();
  let at = 0;
  for (const e of entries) {
    tables.set(e.tag, stream.subarray(at, (at += e.length)));
  }
  const glyf = entries.find((e) => e.tag === "glyf");
  if (glyf !== undefined && glyf.version === 0) {
    const head = tables.get("head");
    if (head === undefined || head.length < 54) throw new Woff2Error("transformed glyf needs head");
    const out = rebuildGlyf(tables.get("glyf") ?? new Uint8Array());
    tables.set("glyf", out.glyf);
    tables.set("loca", out.loca);
    const h = head.slice();
    new DataView(h.buffer).setInt16(50, out.indexFormat); // indexToLocFormat
    tables.set("head", h);
  }
  return assemble(flavor, tables);
}

/** W3C WOFF2 §5.1–§5.3: the seven streams back to `glyf` + `loca`. */
function rebuildGlyf(t: Uint8Array): { glyf: Uint8Array; loca: Uint8Array; indexFormat: number } {
  const h = new Reader(t);
  h.u16();
  const options = h.u16();
  const numGlyphs = h.u16();
  const indexFormat = h.u16();
  const sizes = Array.from({ length: 7 }, () => h.u32());
  type Seven = [Reader, Reader, Reader, Reader, Reader, Reader, Reader];
  const s = sizes.map((n) => new Reader(h.bytes(n))) as Seven; // seven sizes, seven readers
  const [nContour, nPoints, flagS, glyphS, compS, bboxS, instrS] = s;
  const bboxBits = bboxS.bytes(4 * Math.floor((numGlyphs + 31) / 32));
  const overlap = (options & 1) !== 0 ? h.bytes((numGlyphs + 7) >> 3) : null;
  const bit = (m: Uint8Array | null, i: number): boolean =>
    m !== null && ((m[i >> 3] ?? 0) & (0x80 >> (i & 7))) !== 0;

  const out = new Writer(t.length * 2);
  const offsets: number[] = [];
  const w16 = (n: number): void => out.u16(n);
  const put = (b: ArrayLike<number>): void => out.bytes(b);
  for (let g = 0; g < numGlyphs; g += 1) {
    offsets.push(out.n);
    const nc = nContour.i16();
    const explicit = bit(bboxBits, g);
    if (nc === 0) {
      if (explicit) throw new Woff2Error("an empty glyph carries a bbox");
      continue;
    }
    if (nc < 0) {
      if (!explicit) throw new Woff2Error("a composite glyph has no bbox");
      w16(-1);
      for (let k = 0; k < 4; k += 1) w16(bboxS.i16());
      let flags: number;
      let instructions = false;
      do {
        flags = compS.u16();
        instructions ||= (flags & 0x0100) !== 0;
        const n =
          2 +
          ((flags & 1) !== 0 ? 4 : 2) +
          ((flags & 8) !== 0 ? 2 : (flags & 0x40) !== 0 ? 4 : (flags & 0x80) !== 0 ? 8 : 0);
        w16(flags);
        put(compS.bytes(n));
      } while ((flags & 0x20) !== 0);
      if (instructions) {
        const len = glyphS.u255();
        w16(len);
        put(instrS.bytes(len));
      }
    } else {
      const ends: number[] = [];
      let points = 0;
      for (let c = 0; c < nc; c += 1) ends.push((points += nPoints.u255()) - 1);
      const xs: number[] = [];
      const ys: number[] = [];
      const on: boolean[] = [];
      let [x, y] = [0, 0];
      for (let i = 0; i < points; i += 1) {
        const fb = flagS.u8();
        const [dx, dy] = triplet(fb & 0x7f, glyphS);
        xs.push((x += dx));
        ys.push((y += dy));
        on.push((fb & 0x80) === 0);
      }
      const len = glyphS.u255();
      w16(nc);
      if (explicit) for (let k = 0; k < 4; k += 1) w16(bboxS.i16());
      else [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)].forEach(w16);
      ends.forEach(w16);
      w16(len);
      put(instrS.bytes(len));
      const fl: number[] = [];
      const xb: number[] = [];
      const yb: number[] = [];
      for (let i = 0; i < points; i += 1) {
        let f = on[i] === true ? 1 : 0;
        if (i === 0 && bit(overlap, g)) f |= 0x40;
        f |= coord((xs[i] ?? 0) - (xs[i - 1] ?? 0), xb, 0x02, 0x10);
        f |= coord((ys[i] ?? 0) - (ys[i - 1] ?? 0), yb, 0x04, 0x20);
        fl.push(f);
      }
      put(fl);
      put(xb);
      put(yb);
    }
    while (out.n % 4 !== 0) out.bytes([0]);
  }
  offsets.push(out.n);
  const fmt = out.n > 0x1fffe ? 1 : indexFormat;
  const loca = new Uint8Array(offsets.length * (fmt === 1 ? 4 : 2));
  const lv = new DataView(loca.buffer);
  offsets.forEach((o, i) => (fmt === 1 ? lv.setUint32(i * 4, o) : lv.setUint16(i * 2, o / 2)));
  return { glyf: out.done(), loca, indexFormat: fmt };
}

/** One TrueType coordinate delta: flag bits for short / same, bytes appended to `to`. */
function coord(d: number, to: number[], short: number, same: number): number {
  if (d === 0) return same;
  if (d > -256 && d < 256) {
    to.push(Math.abs(d));
    return short | (d > 0 ? same : 0);
  }
  to.push((d >> 8) & 0xff, d & 0xff);
  return 0;
}

/** W3C WOFF2 §5.2 triplet encoding: a flag index and its data bytes to a (dx, dy). */
function triplet(f: number, r: Reader): [number, number] {
  const sign = (bitSet: number, v: number): number => ((bitSet & 1) !== 0 ? v : -v);
  if (f < 10) return [0, sign(f, ((f & 14) << 7) + r.u8())];
  if (f < 20) return [sign(f, (((f - 10) & 14) << 7) + r.u8()), 0];
  if (f < 84) {
    const [b0, b1] = [f - 20, r.u8()];
    return [sign(f, 1 + (b0 & 0x30) + (b1 >> 4)), sign(f >> 1, 1 + ((b0 & 0x0c) << 2) + (b1 & 15))];
  }
  if (f < 120) {
    const b0 = f - 84;
    const dx = sign(f, 1 + (Math.floor(b0 / 12) << 8) + r.u8());
    return [dx, sign(f >> 1, 1 + (((b0 % 12) >> 2) << 8) + r.u8())];
  }
  if (f < 124) {
    const [a, b, c] = [r.u8(), r.u8(), r.u8()];
    return [sign(f, (a << 4) + (b >> 4)), sign(f >> 1, ((b & 15) << 8) + c)];
  }
  const [a, b, c, d] = [r.u8(), r.u8(), r.u8(), r.u8()];
  return [sign(f, (a << 8) + b), sign(f >> 1, (c << 8) + d)];
}

/** An sfnt with sorted, 4-byte aligned tables, their checksums and `head.checkSumAdjustment`. */
function assemble(flavor: number, tables: Map<string, Uint8Array>): Uint8Array<ArrayBuffer> {
  const tags = [...tables.keys()].sort();
  let size = 12 + 16 * tags.length;
  for (const t of tags) size += ((tables.get(t)?.length ?? 0) + 3) & ~3;
  if (size > MAX_SFNT_BYTES) throw new Woff2Error("decoded font exceeds the size bound");
  const out = new Uint8Array(size);
  const v = new DataView(out.buffer);
  const n = tags.length;
  const sel = Math.floor(Math.log2(n));
  [flavor >>> 16, flavor & 0xffff, n, 16 << sel, sel, n * 16 - (16 << sel)].forEach((x, i) =>
    v.setUint16(i * 2, x),
  );
  const sum = (from: number, len: number): number => {
    let acc = 0;
    for (let i = from; i < from + ((len + 3) & ~3); i += 4) acc = (acc + v.getUint32(i)) >>> 0;
    return acc;
  };
  let at = 12 + 16 * n;
  let headAt = -1;
  tags.forEach((tag, i) => {
    const data = tables.get(tag) ?? new Uint8Array();
    out.set(data, at);
    if (tag === "head" && data.length >= 12) v.setUint32((headAt = at) + 8, 0);
    const rec = 12 + i * 16;
    for (let k = 0; k < 4; k += 1) out[rec + k] = tag.charCodeAt(k);
    v.setUint32(rec + 4, sum(at, data.length));
    v.setUint32(rec + 8, at);
    v.setUint32(rec + 12, data.length);
    at += (data.length + 3) & ~3;
  });
  if (headAt >= 0) v.setUint32(headAt + 8, (0xb1b0afba - sum(0, size)) >>> 0);
  return out;
}
