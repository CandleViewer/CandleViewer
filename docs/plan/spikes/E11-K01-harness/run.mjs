// THROWAWAY SPIKE HARNESS (E11-K01 #332). Drives headless Chromium (Playwright from apps/web) over the atlas
// matrix and writes E11-K01-results.json plus the legibility PNGs. The font is a parameter (README.md).
// Run from apps/web:  node ../../docs/plan/spikes/E11-K01-harness/run.mjs --mono <font> --ui <font> [--smoke]
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { cpus, loadavg } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { fontHas, fontVersion } from "./cmap.mjs";
import { FULL, FLOOR, PAIRS, SAMPLE, CELL, FNV } from "./glyphs.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../../..");
const { values: a } = parseArgs({
  options: {
    mono: { type: "string" },
    "mono-name": { type: "string", default: "JetBrains Mono" },
    "mono-weight": { type: "string", default: "400" },
    ui: { type: "string" },
    "ui-name": { type: "string", default: "Inter" },
    "ui-weight": { type: "string", default: "600" },
    "stand-in": { type: "string", default: "" },
    out: { type: "string", default: resolve(here, "..") },
    smoke: { type: "boolean", default: false },
  },
});
if (!a.mono || !a.ui)
  throw new Error("--mono <font file> and --ui <font file> are required (README.md)");
const [nCold, nWarm] = a.smoke ? [1, 2] : [20, 50];
const loadAtStart = loadavg().map((x) => +x.toFixed(2));
const bytes = [readFileSync(a.mono), readFileSync(a.ui)];
const sha = bytes.map((b) => createHash("sha256").update(b).digest("hex"));

// Coverage from the font files (Sc2, BQ-180): borrow a glyph from the other family, else it is missing.
function coverage(sets) {
  const has = [fontHas(bytes[0], sets.mono), fontHas(bytes[1], sets.ui)];
  const other = [fontHas(bytes[1], sets.mono), fontHas(bytes[0], sets.ui)];
  const borrow = [{}, {}];
  const missing = [];
  [sets.mono, sets.ui].forEach((set, fi) => {
    for (const ch of set) {
      if (has[fi].get(ch)) continue;
      if (other[fi].get(ch)) borrow[fi][ch] = 1 - fi;
      else
        missing.push(
          `${fi ? "ui" : "mono"}:U+${ch.codePointAt(0).toString(16).toUpperCase().padStart(4, "0")}`,
        );
    }
  });
  return { borrow, missing };
}

const font = (fi, glyphs, rasterPx, spread, borrow) => ({
  family: fi ? "K01Ui" : "K01Mono",
  url: `/font/${fi}`,
  weight: fi ? a["ui-weight"] : a["mono-weight"],
  glyphs,
  rasterPx,
  spread,
  borrow,
});
const CONFIGS = {
  full: { sets: FULL, mono: [24, 4], ui: [32, 6], sizes: [512, 1024, 2048] },
  floor: { sets: FLOOR, mono: [24, 4], ui: [32, 6], sizes: [512, 1024, 2048] },
  "mono24-full": { sets: { mono: FULL.mono, ui: "" }, mono: [24, 4], ui: [32, 6], sizes: [1024] },
  "mono16-full": { sets: { mono: FULL.mono, ui: "" }, mono: [16, 3], ui: [32, 6], sizes: [1024] },
  "mono32-full": { sets: { mono: FULL.mono, ui: "" }, mono: [32, 6], ui: [32, 6], sizes: [1024] },
};
const cfgOf = (c, size) => {
  const cov = coverage(c.sets);
  return {
    cov,
    cfg: {
      atlasSize: size,
      fonts: [
        font(0, c.sets.mono, ...c.mono, cov.borrow[0]),
        font(1, c.sets.ui, ...c.ui, cov.borrow[1]),
      ],
    },
  };
};

const files = {
  "/edt.mjs": join(repo, "packages/chart-engine/bench/scenes/edt.mjs"),
  "/font/0": a.mono,
  "/font/1": a.ui,
};
for (const f of ["atlas.html", "page.mjs", "legibility.mjs", "atlas-worker.mjs"])
  files[`/h/${f}`] = join(here, f);
const server = createServer((req, res) => {
  const f = files[req.url];
  if (!f) return res.writeHead(404).end();
  const type = f.endsWith(".mjs")
    ? "text/javascript"
    : f.endsWith(".html")
      ? "text/html"
      : "font/ttf";
  res.writeHead(200, { "content-type": type }).end(readFileSync(f));
});
await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
const origin = `http://127.0.0.1:${server.address().port}`;

const { chromium } = createRequire(join(process.cwd(), "package.json"))("@playwright/test");
const browser = await chromium.launch({
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const page = await browser.newPage();
page.on("pageerror", (e) => console.error("pageerror", e.message));
await page.goto(`${origin}/h/atlas.html`);
await page.waitForFunction(() => window.ready === true);
const gpu = await page.evaluate(() => {
  const gl = document.createElement("canvas").getContext("webgl2");
  const ext = gl.getExtension("WEBGL_debug_renderer_info");
  return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
});

// Nearest-rank with floor: at n = 20 the "p95" index is 19, the maximum (the spike note says so).
const pct = (xs, p) =>
  [...xs].sort((x, y) => x - y)[Math.min(xs.length - 1, Math.floor(p * xs.length))];
const st = (xs) => ({
  p50: +pct(xs, 0.5).toFixed(2),
  p95: +pct(xs, 0.95).toFixed(2),
  max: +Math.max(...xs).toFixed(2),
});
const rows = [];
let keep = null;
for (const [name, c] of Object.entries(CONFIGS)) {
  for (const size of a.smoke ? [1024] : c.sizes) {
    if (a.smoke && name !== "full") continue;
    const { cov, cfg } = cfgOf(c, size);
    const runs = [];
    const keepKey = `${name}|${size}`;
    for (let i = 0; i < nCold; i += 1)
      runs.push(
        await page.evaluate(([x, k]) => window.cold(x, k), [cfg, i === 0 ? keepKey : null]),
      );
    const r = runs[0];
    const row = {
      config: name,
      atlas: `${size}x${size}`,
      mono: `${c.mono[0]}px/spread ${c.mono[1]}`,
      ui: c.sets.ui ? `${c.ui[0]}px/spread ${c.ui[1]}` : "-",
      glyphs: r.glyphCount,
      packed: r.packed,
      blank: r.blank,
      dropped: r.dropped,
      missingInFont: cov.missing,
      borrowed: [...Object.keys(cov.borrow[0]), ...Object.keys(cov.borrow[1])],
      shelves: r.rows,
      heightFillPct: +(100 * r.heightFill).toFixed(1),
      occupancyPct: +(100 * r.occupancy).toFixed(1),
      atlasBytes: size * size,
      edtScratchBytes: r.edtScratchBytes,
      fontLoadMs: st(runs.map((x) => x.ms.fontLoad)),
      genMs: st(runs.map((x) => x.ms.gen)),
      genHotMs: st(runs.map((x) => x.ms.genHot)),
      stageP50Ms: Object.fromEntries(
        ["raster", "edt", "packBlit"].map((k) => [
          k,
          +pct(
            runs.map((x) => x.ms[k]),
            0.5,
          ).toFixed(2),
        ]),
      ),
      glyphSetHash: FNV(c.sets.mono + "|" + c.sets.ui),
    };
    if (name === "full" || a.smoke)
      row.warm = await page.evaluate(([k, n]) => window.warm(k, n), [keepKey, nWarm]);
    const covered = cov.missing.length === 0 && r.dropped === 0;
    const warmP95 = row.warm?.usedRows.openPlusGet.p95;
    row.verdict = !covered
      ? `REJECTED (coverage: ${r.dropped} dropped, ${cov.missing.length} missing in font)`
      : row.genMs.p95 > 60
        ? "FAIL (cold gen p95 > 60 ms)"
        : warmP95 !== undefined && warmP95 > 5
          ? "FAIL (warm p95 > 5 ms)"
          : "PASS";
    rows.push(row);
    console.log(
      JSON.stringify({
        config: name,
        atlas: row.atlas,
        genMs: row.genMs,
        warm: row.warm,
        verdict: row.verdict,
      }),
    );
    if (name === "full" && size === 1024) keep = { key: keepKey, cfg };
    if (name === "mono16-full") keep.m16 = { key: keepKey, cfg };
  }
}

// Legibility on the recommended atlas (full, 1024²), plus the 16 px base at 10 / 11 px for comparison.
const dprs = a.smoke ? [1] : [1, 1.25, 2];
const legArgs = (k, cases, images) => ({
  keep: k.key,
  size: k.cfg.atlasSize,
  font: k.cfg.fonts[0],
  cases,
  pairs: PAIRS.map((p) => [...p]),
  sample: SAMPLE,
  cellSet: CELL,
  images,
});
const cases = [10, 11, 13].flatMap((px) => dprs.map((dpr) => ({ px, dpr })));
const leg = await page.evaluate((x) => window.legibility(x), legArgs(keep, cases, true));
const leg16 = keep.m16
  ? await page.evaluate(
      (x) => window.legibility(x),
      legArgs(
        keep.m16,
        [10, 11].flatMap((px) => [1, 1.25].map((dpr) => ({ px, dpr }))),
        false,
      ),
    )
  : null;
await browser.close();
server.close();

const out = {
  ticket: "E11-K01 (#332)",
  generatedAt: new Date().toISOString(),
  host: {
    cpus: cpus().length,
    cpuModel: cpus()[0]?.model,
    loadavgAtStart: loadAtStart,
    loadavgAtEnd: loadavg().map((x) => +x.toFixed(2)),
    node: process.version,
  },
  browser: { chromium: browser.version(), webgl: gpu },
  fonts: [
    {
      role: "mono (cells, axis, GL pills)",
      design: `${a["mono-name"]} ${a["mono-weight"]}`,
      file: a.mono.split("/").pop(),
      version: fontVersion(bytes[0]),
      sha256: sha[0],
    },
    {
      role: "ui (watermark)",
      design: `${a["ui-name"]} ${a["ui-weight"]}`,
      file: a.ui.split("/").pop(),
      version: fontVersion(bytes[1]),
      sha256: sha[1],
    },
  ],
  standIn: a["stand-in"] || null,
  samples: { cold: nCold, warm: nWarm },
  gates: { genP95Ms: 60, warmP95Ms: 5, ssimMinAt10pxDpr1: 0.9, pairRatioMin: 0.8 },
  rows,
  legibility: { atlas: "full 1024x1024, mono 24px/spread 4", ...leg, png: undefined },
  legibilityMono16: leg16 && { atlas: "mono 16px/spread 3", results: leg16.results },
};
const outFile = a.smoke ? "/tmp/E11-K01-smoke.json" : join(a.out, "E11-K01-results.json");
writeFileSync(outFile, JSON.stringify(out, null, 2) + "\n");
if (!a.smoke) {
  mkdirSync(join(a.out, "E11-K01/img"), { recursive: true });
  for (const [dpr, url] of Object.entries(leg.png))
    writeFileSync(
      join(a.out, `E11-K01/img/legibility-dpr${dpr}.png`),
      Buffer.from(url.split(",")[1], "base64"),
    );
}
console.log(`wrote ${outFile}`);
