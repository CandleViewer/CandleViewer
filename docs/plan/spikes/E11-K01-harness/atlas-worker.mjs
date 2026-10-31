// THROWAWAY SPIKE HARNESS (E11-K01). The §3.7 pipeline in a worker: FontFace from bytes -> OffscreenCanvas
// fillText per glyph -> tight bbox -> two-pass Felzenszwalb EDT (bench/scenes/edt.mjs, unchanged) -> shelf
// pack (height desc, codepoint asc; BQ-183) into one R8 texture. Overflow is counted, never dropped (Sc2).
import { bitmapToSdf } from "/edt.mjs";

const now = () => performance.now();

async function loadFace({ family, url, weight }) {
  const bytes = await (await fetch(url)).arrayBuffer();
  const face = new FontFace(family, bytes, { weight: String(weight) });
  self.fonts.add(face);
  await face.load();
}

// One canvas and one getImageData per family: every glyph is drawn into its own grid cell, then cropped
// to its tight ink bbox and padded by the spread.
function rasteriseAll(f, list) {
  const cell = Math.ceil(f.rasterPx * 2) + 2 * (f.spread + 2);
  const cols = 16;
  const cv = new OffscreenCanvas(cols * cell, Math.ceil(list.length / cols) * cell || 1);
  const ctx = cv.getContext("2d", { willReadFrequently: true });
  const pad = f.spread + 2;
  const base = pad + Math.ceil(f.rasterPx * 1.1);
  const pos = list.map(({ ch, src }, i) => {
    ctx.font = `${src.weight} ${f.rasterPx}px "${src.family}"`;
    const [cx, cy] = [(i % cols) * cell, Math.floor(i / cols) * cell];
    ctx.fillText(ch, cx + pad, cy + base);
    return { ch, cx, cy, advance: ctx.measureText(ch).width };
  });
  const { data } = ctx.getImageData(0, 0, cv.width, cv.height);
  const W = cv.width;
  const s = f.spread;
  return pos.map(({ ch, cx, cy, advance }) => {
    let [x0, y0, x1, y1] = [cx + cell, cy + cell, -1, -1];
    for (let y = cy; y < cy + cell; y += 1)
      for (let x = cx; x < cx + cell; x += 1)
        if (data[(y * W + x) * 4 + 3] > 0) {
          if (x < x0) x0 = x;
          if (x > x1) x1 = x;
          if (y < y0) y0 = y;
          if (y > y1) y1 = y;
        }
    if (x1 < 0) return { ch, w: 0, h: 0, ox: 0, oy: 0, advance, bitmap: null };
    const [w, h] = [x1 - x0 + 1 + 2 * s, y1 - y0 + 1 + 2 * s];
    const bitmap = new Uint8Array(w * h);
    for (let y = y0; y <= y1; y += 1)
      for (let x = x0; x <= x1; x += 1)
        bitmap[(y - y0 + s) * w + (x - x0 + s)] = data[(y * W + x) * 4 + 3];
    return { ch, w, h, ox: x0 - s - cx - pad, oy: y0 - s - cy - base, advance, bitmap };
  });
}

function shelfPack(items, size, pad = 1) {
  const sorted = items.filter((g) => g.w > 0).sort((a, b) => b.h - a.h || a.key - b.key);
  let [x, y, shelfH, rows, dropped] = [0, 0, 0, 1, 0];
  for (const g of sorted) {
    if (x + g.w + pad > size) [x, y, shelfH, rows] = [0, y + shelfH + pad, 0, rows + 1];
    if (y + g.h + pad > size) {
      dropped += 1;
      continue;
    }
    [g.x, g.y] = [x, y];
    x += g.w + pad;
    shelfH = Math.max(shelfH, g.h);
  }
  return { usedHeight: y + shelfH, rows, dropped };
}

function build(cfg) {
  const t1 = now();
  const glyphs = [];
  cfg.fonts.forEach((f, fi) => {
    const list = [...f.glyphs].map((ch) => ({
      ch,
      src: f.borrow?.[ch] === undefined ? f : cfg.fonts[f.borrow[ch]],
    }));
    for (const g of rasteriseAll(f, list))
      glyphs.push({ ...g, font: fi, key: fi * 0x110000 + g.ch.codePointAt(0) });
  });
  const t2 = now();
  for (const g of glyphs)
    if (g.bitmap) g.sdf = bitmapToSdf(g.bitmap, g.w, g.h, cfg.fonts[g.font].spread);
  const t3 = now();
  const pack = shelfPack(glyphs, cfg.atlasSize);
  const texture = new Uint8Array(cfg.atlasSize * cfg.atlasSize);
  let inked = 0;
  for (const g of glyphs) {
    if (!g.sdf || g.x === undefined) continue;
    inked += g.w * g.h;
    for (let y = 0; y < g.h; y += 1)
      texture.set(g.sdf.subarray(y * g.w, (y + 1) * g.w), (g.y + y) * cfg.atlasSize + g.x);
  }
  const t4 = now();
  return {
    glyphs,
    pack,
    texture,
    inked,
    ms: { raster: t2 - t1, edt: t3 - t2, packBlit: t4 - t3, gen: t4 - t1 },
  };
}

self.onmessage = async ({ data: cfg }) => {
  const t0 = now();
  for (const f of cfg.fonts) await loadFace(f);
  const fontLoad = now() - t0;
  const { glyphs, pack, texture, inked, ms } = build(cfg);
  // A second build in the same worker separates JIT warm-up from the algorithm's own cost (`genHot`).
  const genHot = build(cfg).ms.gen;
  const metrics = glyphs.map(({ ch, font, w, h, ox, oy, advance, x, y }) => ({
    ch,
    font,
    w,
    h,
    ox,
    oy,
    advance,
    x,
    y,
  }));
  self.postMessage(
    {
      ms: { fontLoad, ...ms, genHot },
      glyphCount: glyphs.length,
      packed: glyphs.filter((g) => g.x !== undefined).length,
      blank: glyphs.filter((g) => g.w === 0).length,
      ...pack,
      occupancy: inked / cfg.atlasSize ** 2,
      heightFill: pack.usedHeight / cfg.atlasSize,
      edtScratchBytes: Math.max(...glyphs.map((g) => g.w * g.h)) * 8 * 2,
      metrics,
      texture: texture.buffer,
    },
    [texture.buffer],
  );
};
