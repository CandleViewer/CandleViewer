// E24-S05 (#780): the feed's formats — the notional rounded exactly on the decimal string (review A M2), and the
// row time dated on a day change.
import { describe, expect, it } from "vitest";
import { feedTimeIn, notional2 } from "../../../../src/features/derivatives/liquidations/ui/format";

describe("notional2", () => {
  it.each([
    ["202473.6", "202,473.60"],
    ["41210.10", "41,210.10"],
    ["0.005", "0.01"],
    ["0.004999", "0.00"],
    ["1.234", "1.23"],
    ["2.675", "2.68"], // a float would read 2.67
    ["999.995", "1,000.00"],
    ["7", "7.00"],
    ["123456789012345678901234567890.125", "123,456,789,012,345,678,901,234,567,890.13"],
  ])("%s reads %s", (value, text) => {
    expect(notional2(value)).toBe(text);
  });

  it("leaves a value that is not a plain decimal as sent", () => {
    expect(notional2("1e5")).toBe("1e5");
  });
});

describe("feedTimeIn", () => {
  const ref = Date.parse("2026-10-21T09:14:02Z");
  it("drops the date on the newest row's day and names it on another", () => {
    expect(feedTimeIn(Date.parse("2026-10-21T00:00:00Z"), ref)).toBe("00:00:00");
    expect(feedTimeIn(Date.parse("2026-10-20T23:59:58Z"), ref)).toBe("20 Oct 23:59:58");
  });
});
