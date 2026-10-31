// THROWAWAY SPIKE HARNESS (E11-K01). Page-side entry points that run.mjs drives through Playwright.
import { legibility } from "/h/legibility.mjs";

/** Cold generation: a fresh worker per sample, so no font, JIT or canvas state carries over (BQ-178). */
window.kept = {};
const generate = (cfg) =>
  new Promise((resolve, reject) => {
    const w = new Worker("/h/atlas-worker.mjs", { type: "module" });
    w.onmessage = ({ data }) => (w.terminate(), resolve(data));
    w.onerror = (e) => (w.terminate(), reject(new Error(e.message)));
    w.postMessage(cfg);
  });
/** The texture stays in the page (`kept`); Node gets numbers and metrics only. */
window.cold = async (cfg, keep) => {
  const r = await generate(cfg);
  if (keep) window.kept[keep] = r;
  return { ...r, texture: undefined };
};

const req = (r) =>
  new Promise((ok, ko) => ((r.onsuccess = () => ok(r.result)), (r.onerror = () => ko(r.error))));
const openDb = () => {
  const r = indexedDB.open("cv-k01-atlas", 1);
  r.onupgradeneeded = () => r.result.createObjectStore("atlas");
  return req(r);
};
const pct = (xs, p) =>
  [...xs].sort((a, b) => a - b)[Math.min(xs.length - 1, Math.floor(p * xs.length))];
const stats = (xs) => ({
  p50: pct(xs, 0.5),
  p95: pct(xs, 0.95),
  max: Math.max(...xs),
  n: xs.length,
});

/** Warm load: the real IndexedDB, a record shaped like E11-S11's `{ atlasBytes, metrics, checksum }`.
 * Two record shapes: the whole size² texture, and only the rows the packer used (`usedHeight`). */
window.warm = async (keep, n) => {
  const atlas = window.kept[keep];
  const size = Math.sqrt(atlas.texture.byteLength);
  const shapes = {
    full: atlas.texture,
    usedRows: atlas.texture.slice(0, (atlas.usedHeight + 1) * size),
  };
  const out = {};
  for (const [shape, bytes] of Object.entries(shapes)) {
    const key = `${keep}|${shape}`;
    let db = await openDb();
    await req(
      db
        .transaction("atlas", "readwrite")
        .objectStore("atlas")
        .put({ atlasBytes: bytes, metrics: atlas.metrics, checksum: "-" }, key),
    );
    db.close();
    const get = async (conn) => {
      const v = await req(conn.transaction("atlas").objectStore("atlas").get(key));
      if (v.atlasBytes.byteLength !== bytes.byteLength) throw new Error("short read");
    };
    const [reuse, fresh] = [[], []];
    db = await openDb();
    await get(db); // first read after the put is not a launch read; discarded
    for (let i = 0; i < n; i += 1) {
      const t = performance.now();
      await get(db);
      reuse.push(performance.now() - t);
    }
    db.close();
    for (let i = 0; i < n; i += 1) {
      const t = performance.now();
      const c = await openDb();
      await get(c);
      fresh.push(performance.now() - t);
      c.close();
    }
    out[shape] = {
      recordBytes: bytes.byteLength,
      getOnOpenConnection: stats(reuse),
      openPlusGet: stats(fresh),
    };
  }
  return out;
};

window.legibility = legibility;
window.stats = stats;
window.ready = true;
