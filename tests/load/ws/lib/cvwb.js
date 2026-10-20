/* CVWB decoder for the E17-Q03 k6 client: a hand port of packages/protocol/src/runtime (23 3.4).
 *
 * Pure, no k6 imports, so Node loads it too (tests/load/ws/lib/cvwb.check.mjs). Integers are JS
 * Numbers: a u64 or i64 is `hi * 2^32 + lo`, exact up to 2^53 (`stats.imprecise` counts a value
 * beyond, which prices and sizes at load never reach). Number, not BigInt, because the client decodes
 * every frame in an interpreter. Parity with the production decoder is pinned by decoding the golden
 * vectors (`checkVectors`), which k6's setup() runs before a single socket opens.
 *
 * Every offset and stride below is the one declared in packages/protocol/cvwb-layout.json.
 */

export const MAGIC = 0x43565742;
export const HEADER_BYTES = 24;
const TWO32 = 4294967296;
const SAFE = 9007199254740991;

export const stats = { imprecise: 0 };

/** `code` is the local diagnostic; every one maps to `frame_malformed` on the wire (23 10). */
export class CvwbError extends Error {
  constructor(message, code) {
    super(message);
    this.code = code || "frame_malformed";
  }
}

function u64(dv, at) {
  const v = dv.getUint32(at + 4, true) * TWO32 + dv.getUint32(at, true);
  if (v > SAFE) stats.imprecise++;
  return v;
}

function i64(dv, at) {
  const v = dv.getInt32(at + 4, true) * TWO32 + dv.getUint32(at, true);
  if (Math.abs(v) > SAFE) stats.imprecise++;
  return v;
}

/** kind -> [format_version, record bytes, exact length rule] */
const KINDS = {
  1: [1, 17, false],
  2: [1, 17, false],
  3: [1, 22, false],
  4: [2, 85, true],
  5: [2, 33, false],
  6: [1, 16, false],
};
const GROUP_PREFIX = 28;
const HEATMAP_PREFIX = 24;
const TRAILER = 16;

function fits(count, stride, available, what) {
  if (count * stride > available)
    throw new CvwbError(`${what}: ${count} x ${stride} bytes exceed the ${available} left`);
}

/** The common header, with the magic, kind and (kind, version) pair validated. */
export function parseHeader(dv) {
  if (dv.byteLength < HEADER_BYTES)
    throw new CvwbError(`too short for the header (${dv.byteLength} bytes)`);
  if (dv.getUint32(0, true) !== MAGIC) throw new CvwbError("bad magic");
  const version = dv.getUint8(4);
  const kind = dv.getUint8(5);
  const spec = KINDS[kind];
  if (spec === undefined) throw new CvwbError(`unknown body_kind ${kind}`, "unsupported_body_kind");
  if (version !== spec[0])
    throw new CvwbError(
      `(body_kind ${kind}, format_version ${version}) is unknown`,
      "unsupported_format_version",
    );
  const flags = dv.getUint8(6);
  return {
    kind,
    version,
    flags,
    partial: (flags & 8) !== 0,
    coalesced: (flags & 2) !== 0,
    priceScale: dv.getUint8(7),
    qtyScale: dv.getUint8(8),
    count: dv.getUint32(12, true),
    tsBase: u64(dv, 16),
  };
}

/**
 * A body decoded into arrays of Numbers, fields in declaration order: `records` (book (side, price,
 * size); trades (ts_offset, price, size, side, flags); bars (generation, index, ts_offset, o, h, l, c,
 * v, turnover, trades, delta, flags); heatmap rows (bid, ask)), plus `trailer` (book snapshot: xu,
 * xseq), `prefix` (heatmap: ts_offset, price_min, price_step) or `groups` (footprint).
 */
export function decode(buf) {
  const dv = new DataView(buf);
  const h = parseHeader(dv);
  const [, stride, exact] = KINDS[h.kind];
  const out = { ...h, records: [], trailer: null, prefix: null, groups: null };
  let at = HEADER_BYTES;
  if (h.kind === 5) {
    fits(h.count, GROUP_PREFIX, dv.byteLength - at, "footprint groups");
    out.groups = [];
    for (let g = 0; g < h.count; g++) {
      if (at + GROUP_PREFIX > dv.byteLength)
        throw new CvwbError(`footprint group ${g} runs past the buffer`);
      const prefix = [
        u64(dv, at),
        u64(dv, at + 8),
        dv.getUint32(at + 16, true),
        dv.getUint8(at + 24),
      ];
      const cells = dv.getUint32(at + 20, true);
      at += GROUP_PREFIX;
      fits(cells, stride, dv.byteLength - at, `footprint group ${g}`);
      const rows = [];
      for (let i = 0; i < cells; i++, at += stride) {
        rows.push([
          i64(dv, at),
          u64(dv, at + 8),
          u64(dv, at + 16),
          dv.getUint32(at + 24, true),
          dv.getUint8(at + 28),
        ]);
      }
      out.groups.push([prefix, rows]);
    }
    return out;
  }
  let count = h.count;
  if (h.kind === 6) {
    if (at + HEATMAP_PREFIX > dv.byteLength)
      throw new CvwbError("heatmap column shorter than its prefix");
    out.prefix = [dv.getUint32(at, true), i64(dv, at + 4), i64(dv, at + 12)];
    count = dv.getUint32(at + 20, true);
    at += HEATMAP_PREFIX;
  }
  fits(count, stride, dv.byteLength - at, `body_kind ${h.kind}`);
  if (exact && dv.byteLength !== at + count * stride) {
    throw new CvwbError(`bars body is ${dv.byteLength} bytes, expected ${at + count * stride}`);
  }
  for (let i = 0; i < count; i++, at += stride) {
    if (h.kind <= 2) {
      const side = dv.getUint8(at);
      if (side > 1) throw new CvwbError(`invalid book side ${side} at record ${i}`);
      out.records.push([side, i64(dv, at + 1), u64(dv, at + 9)]);
    } else if (h.kind === 3) {
      const side = dv.getUint8(at + 20);
      if (side > 1) throw new CvwbError(`invalid trade side ${side} at record ${i}`);
      out.records.push([
        dv.getUint32(at, true),
        i64(dv, at + 4),
        u64(dv, at + 12),
        side,
        dv.getUint8(at + 21),
      ]);
    } else if (h.kind === 4) {
      out.records.push([
        u64(dv, at),
        u64(dv, at + 8),
        dv.getUint32(at + 16, true),
        i64(dv, at + 20),
        i64(dv, at + 28),
        i64(dv, at + 36),
        i64(dv, at + 44),
        u64(dv, at + 52),
        u64(dv, at + 60),
        dv.getUint32(at + 68, true),
        i64(dv, at + 72),
        dv.getUint8(at + 80),
      ]);
    } else {
      out.records.push([u64(dv, at), u64(dv, at + 8)]);
    }
  }
  if (h.kind === 1) {
    if (at + TRAILER > dv.byteLength)
      throw new CvwbError("book snapshot missing its xu/xseq trailer");
    out.trailer = [u64(dv, at), u64(dv, at + 8)];
  }
  return out;
}

/** Hex text to the ArrayBuffer `decode` takes (the golden vectors are hex). */
export function hexToBuffer(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) bytes[i] = parseInt(hex.substr(i * 2, 2), 16);
  return bytes.buffer;
}

/** `Number("18446744073709551615")` rounds once, as `hi * 2^32 + lo` does: equal for every field. */
const same = (got, want) => got === Number(want);

/** Decode every golden vector and list each mismatch (empty: the port agrees with the vectors). */
export function checkVectors(vectors) {
  const bad = [];
  for (const v of vectors) {
    let d;
    try {
      d = decode(hexToBuffer(v.hex));
    } catch (e) {
      bad.push(`${v.name}: ${e.message}`);
      continue;
    }
    const head = [
      [d.kind, v.body_kind],
      [d.flags, v.flags],
      [d.priceScale, v.price_scale],
      [d.qtyScale, v.qty_scale],
    ];
    if (!same(d.tsBase, v.ts_base_ms) || head.some(([a, b]) => a !== b))
      bad.push(`${v.name}: header`);
    const rows = (got, want, label) => {
      if (got.length !== want.length)
        bad.push(`${v.name}: ${label} count ${got.length} != ${want.length}`);
      else
        got.forEach((r, i) =>
          r.forEach((x, j) => {
            if (!same(x, want[i][j])) bad.push(`${v.name}: ${label}[${i}][${j}]`);
          }),
        );
    };
    rows(d.records, v.records, "records");
    if (v.trailer) rows([d.trailer], [v.trailer], "trailer");
    if (v.prefix) rows([d.prefix], [v.prefix], "prefix");
    if (v.groups) {
      rows(
        d.groups.map((g) => g[0]),
        v.groups.map((g) => g[0]),
        "group prefix",
      );
      d.groups.forEach((g, i) => rows(g[1], v.groups[i][1], `group ${i} cells`));
    }
  }
  return bad;
}
