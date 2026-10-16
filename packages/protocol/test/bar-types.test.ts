import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import type { bars } from "../src/generated/index.js";
import type { ws } from "../src/generated/index.js";

// E12-T01: the TS bar model is generated from the Pydantic models (via the committed
// JSON Schema). Regenerating must reproduce the committed file byte-for-byte. The fresh copy goes to a
// temp dir: rewriting the tracked file in place raced the generated-guard test (#2965).

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
const outPath = join(packageRoot, "src", "generated", "bars", "index.ts");
const vectorsPath = join(packageRoot, "..", "fixtures", "golden", "bars", "spec_hash_vectors.json");

describe("generated bar types", () => {
  it("match a fresh generation from bar-model.schema.json (drift check)", () => {
    const committed = readFileSync(outPath, "utf8").split("\r\n").join("\n");
    const dir = mkdtempSync(join(tmpdir(), "cv-bar-types-"));
    try {
      const freshPath = join(dir, "index.ts");
      execFileSync("node", [join(packageRoot, "scripts", "generate-bar-types.mjs"), freshPath], {
        cwd: packageRoot,
        stdio: "pipe",
      });
      const fresh = readFileSync(freshPath, "utf8").split("\r\n").join("\n");
      expect(fresh).toBe(committed);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("type every golden spec and a Bar compatible with the BarsBatch wire shape", () => {
    const doc = JSON.parse(readFileSync(vectorsPath, "utf8")) as {
      vectors: { canonical_json: string }[];
    };
    const specs: bars.BarSpec[] = doc.vectors.map((v) => JSON.parse(v.canonical_json));
    expect(specs.length).toBeGreaterThan(0);
    const bar: bars.Bar = {
      spec_hash: "a".repeat(64),
      symbol: "BTCUSDT",
      index: 0,
      open_time: 1_789_132_000_000_000,
      close_time: 1_789_132_060_000_000,
      open: "100",
      high: "101",
      low: "99",
      close: "100.5",
      volume: "3",
      buy_volume: "2",
      sell_volume: "1",
      delta: "1",
      min_delta: "-1",
      max_delta: "2",
      trade_count: 4,
      turnover: "300",
      vwap: "100",
      closed: true,
      partial: false,
      gap_before: false,
    };
    const update: bars.BarUpdate = { kind: "close", bar };
    type WireBar = ws.BarsSymbolBarTypeParam["bars"][number];
    const wire: WireBar = {
      generation: 0,
      index: bar.index,
      t_ms: Math.floor(bar.open_time / 1000),
      o: bar.open,
      h: bar.high,
      l: bar.low,
      c: bar.close,
      v: bar.volume,
      confirm: update.bar.closed,
    };
    expect(wire.c).toBe("100.5");
  });
});
