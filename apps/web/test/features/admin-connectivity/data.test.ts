import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { COPY } from "../../../src/features/admin-connectivity/copy";
import {
  ERROR_REPORT,
  SERVED_REPORT,
  UNAVAILABLE_REPORT,
} from "../../../src/features/admin-connectivity/fixtures";
import {
  NOT_CONNECTED,
  formatFigure,
  formatPercent,
} from "../../../src/features/admin-connectivity/format";
import { SLICES, sliceFlags, sliceOn } from "../../../src/features/admin-connectivity/flags";
import { emitPanelViewed, noopAnalytics } from "../../../src/features/admin-connectivity/analytics";
import {
  opaqueKey,
  rateBudgetRead,
  rateBudgetRows,
} from "../../../src/features/admin-connectivity/rateBudget";
import { fill, parts, printable } from "../../../src/features/admin-connectivity/text";

const PACK = JSON.parse(
  readFileSync(
    resolve(import.meta.dirname, "../../../../../docs/design/E08/E08-D13-copy.json"),
    "utf8",
  ),
) as { strings: Record<string, { text: string }> };

describe("the copy deck is the pack's, byte for byte (E08-D13)", () => {
  const entries = Object.entries(COPY);
  it("has the whole d09 deck", () => {
    const packKeys = Object.keys(PACK.strings).filter((k) => k.startsWith("d09."));
    expect(entries.map(([k]) => `d09.${k}`).sort()).toEqual(packKeys.sort());
  });
  it.each(entries)("%s", (key, text) => {
    expect(text).toBe(PACK.strings[`d09.${key}`]?.text);
  });
});

describe("text helpers", () => {
  it("fills a slot from a served value and drops a line with an open slot", () => {
    expect(fill("Wait {40} s.", { "40": 12 })).toBe("Wait 12 s.");
    expect(fill("Wait {40} s.")).toBeNull();
  });
  it("prints only what is filled: no deck example ever stands in for a figure", () => {
    const open = printable("W-16").join(" ");
    expect(open).not.toContain("14:42:05");
    expect(open).not.toContain("8m 20s");
    expect(printable("W-16", { "14:42:05": "14:50:00", "8m 20s": "2m" }).join(" ")).toContain(
      "Our hold ends at 14:50:00 (in 2m)",
    );
    expect(parts("W-16")).toHaveLength(4);
  });
});

describe("figures", () => {
  it("never read 0 for a figure that is not served", () => {
    for (const v of [undefined, null, Number.NaN, Number.POSITIVE_INFINITY])
      expect(formatFigure(v, "requests")).toBe(NOT_CONNECTED);
    expect(formatPercent(null)).toBe("Not connected yet");
  });
  it("show a served zero as a measured zero, with its unit", () => {
    expect(formatFigure(0, "requests")).toBe("0 requests");
  });
});

describe("the slice flags", () => {
  it("are off by default and on only for the build variable 1", () => {
    expect(Object.values(sliceFlags({})).every((v) => !v)).toBe(true);
    expect(sliceOn({ [SLICES.clock]: "1" }, "clock")).toBe(true);
    expect(sliceOn({ [SLICES.clock]: "true" }, "clock")).toBe(false);
    expect(sliceOn({ [SLICES.clock]: "1" }, "reserve")).toBe(false);
  });
  it("are off in the test build", () => {
    expect(Object.values(sliceFlags()).every((v) => !v)).toBe(true);
  });
});

describe("the served rate_budget[] (CapacityReport)", () => {
  it("maps each served status to a read: unknown words tolerated as unavailable", () => {
    expect(rateBudgetRead(undefined)).toBe("loading");
    expect(rateBudgetRead(undefined, true)).toBe("failed");
    expect(rateBudgetRead(SERVED_REPORT)).toBe("ok");
    expect(rateBudgetRead(ERROR_REPORT)).toBe("error");
    expect(rateBudgetRead(UNAVAILABLE_REPORT)).toBe("unavailable");
    expect(rateBudgetRead({})).toBe("unavailable");
    expect(rateBudgetRead({ rate_budget_status: { status: "later" as unknown as "ok" } })).toBe(
      "unavailable",
    );
  });
  it("serves rows only when the slice is ok, with no id and no served detail", () => {
    expect(rateBudgetRows(UNAVAILABLE_REPORT)).toEqual([]);
    expect(rateBudgetRows(ERROR_REPORT)).toEqual([]);
    const rows = rateBudgetRows(SERVED_REPORT);
    expect(rows.map((r) => r.label)).toEqual(["Main", "Swing"]);
    expect(JSON.stringify(rows)).not.toContain("detail");
  });
  it("keys a row opaquely and stably from the wire id", () => {
    const id = "0b9d7c1e-0000-4000-8000-000000000001";
    expect(opaqueKey(id)).toBe(opaqueKey(id));
    expect(opaqueKey(id)).not.toContain(id);
    expect(opaqueKey(id)).not.toBe(opaqueKey("another"));
    const rows = rateBudgetRows({
      rate_budget_status: { status: "ok" },
      rate_budget: [{ exchange_account_id: id, label: "Main", limit_per_minute: 1 }],
    });
    expect(rows[0]?.key).toBe(opaqueKey(id));
    expect(rows[0]?.peakUsedPerMinute).toBeNull();
  });
});

describe("the analytics port", () => {
  it("is a no-op by default and carries ids and counts only", () => {
    const seen: unknown[] = [];
    emitPanelViewed({ panelViewed: (e) => seen.push(e) }, "S-19", 6, 0);
    expect(seen).toEqual([
      { name: "connectivity.panel_viewed", state: "S-19", slicesOn: 6, slicesServed: 0 },
    ]);
    expect(() => emitPanelViewed(noopAnalytics, "S-01", 1, 1)).not.toThrow();
  });
});
