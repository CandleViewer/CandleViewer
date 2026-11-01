import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  FootprintCellContent,
  ImbalanceMark,
  SideLegend,
  SideMark,
  SignedValue,
} from "../../../src/chart/a11y/marks";
import { atSignature, expectCssPattern, expectNoHueAlone, visualSignature } from "./noHueAlone";

const CSS = readFileSync(
  resolve(import.meta.dirname, "../../../src/chart/a11y/orderflowMarks.css"),
  "utf8",
);
const mount = (node: JSX.Element): HTMLElement => render(node).container;

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

describe("no-hue-alone (05 §4): every state survives without colour", () => {
  it("footprint: delta −8 and +8, flagged and plain cells", () => {
    expectNoHueAlone(
      "footprint",
      {
        plus: mount(
          <FootprintCellContent
            cell={{ price: "1", bid: "2", ask: "10", delta: "8", imbalance: null }}
          />,
        ),
        minus: mount(
          <FootprintCellContent
            cell={{ price: "1", bid: "10", ask: "2", delta: "-8", imbalance: null }}
          />,
        ),
        flagged: mount(
          <FootprintCellContent
            cell={{ price: "1", bid: "2", ask: "10", delta: "8", imbalance: "ask" }}
          />,
        ),
        bidFlag: mount(
          <FootprintCellContent
            cell={{ price: "1", bid: "2", ask: "10", delta: "8", imbalance: "bid" }}
          />,
        ),
      },
      CSS,
    );
  });

  it("CVD: rising, falling and flat", () => {
    expectNoHueAlone("cvd", {
      up: mount(<SignedValue value="120" />),
      down: mount(<SignedValue value="-120" />),
      flat: mount(<SignedValue value="0" />),
    });
  });

  it("tape: a buy and a sell print of one size", () => {
    const print = (side: "buy" | "sell"): JSX.Element => (
      <span>
        <SideMark side={side} /> 0.5
      </span>
    );
    expectNoHueAlone("tape", { buy: mount(print("buy")), sell: mount(print("sell")) });
  });

  it("imbalance tracker: bid and ask rows of one size", () => {
    const row = (side: "bid" | "ask"): JSX.Element => (
      <span>
        <ImbalanceMark side={side} /> <SignedValue value={side === "bid" ? "-40" : "40"} />
      </span>
    );
    expectNoHueAlone("imbalance-tracker", { bid: mount(row("bid")), ask: mount(row("ask")) }, CSS);
  });

  it("the check fails a hue-only pair (it would catch a regression)", () => {
    const up = mount(<span className="cv-of-signed--up">8</span>);
    const down = mount(<span className="cv-of-signed--down">8</span>);
    expect(() => expectNoHueAlone("bad", { up, down })).toThrow(/by colour alone/);
    expect(() =>
      expectNoHueAlone("empty", { blank: mount(<span className="cv-of-side--bid" />) }),
    ).toThrow(/no non-colour channel/);
  });

  it("an accessible name is not a visual channel: a pair differing only by aria-label fails", () => {
    const a = mount(<span aria-label="bid imbalance">8</span>);
    const b = mount(<span aria-label="ask imbalance">8</span>);
    expect(atSignature(a)).not.toBe(atSignature(b));
    expect(() => expectNoHueAlone("label-only", { a, b })).toThrow(/by colour alone/);
  });

  it("a declared pattern counts only when the stylesheet draws it", () => {
    const el = mount(
      <span className="cv-of-signed--up" data-cv-pattern="dashed">
        8
      </span>,
    );
    expect(() => visualSignature(el, CSS)).toThrow(/declared but not drawn/);
    const hidden = mount(
      <span>
        8<span className="cv-visually-hidden">ask</span>
      </span>,
    );
    expect(visualSignature(hidden)).toBe("8");
  });
});

describe("the marks' channels", () => {
  it("a signed value carries its sign and an aria-hidden glyph; flat has no glyph", () => {
    const up = mount(<SignedValue value="8" />);
    expect(up.textContent).toBe("▲+8");
    expect(up.querySelector("[aria-hidden='true']")?.textContent).toBe("▲");
    expect(mount(<SignedValue value="-8" />).textContent).toBe("▼−8");
    expect(mount(<SignedValue value="0" />).textContent).toBe("+0");
  });

  it("an imbalance reads as its word and declares the dashed pattern, drawn in CSS for grayscale and forced colours", () => {
    const el = mount(<ImbalanceMark side="ask" />);
    expect(el.textContent).toContain("Ask imbalance");
    expect(visualSignature(el, CSS)).toContain("pattern:dashed");
    expectCssPattern(CSS, ".cv-of-imbalance", /border:[^;]*dashed/);
    expectCssPattern(CSS, ".cv-of-cell--imbalance", /border:[^;]*dashed/);
    expect(CSS).toMatch(
      /@media \(forced-colors: active\)[\s\S]*\.cv-of-cell--imbalance[\s\S]*CanvasText/,
    );
  });

  it("the CSS uses tokens only: no hex, rgb or named colour outside forced colours", () => {
    const outside = CSS.replace(/@media \(forced-colors: active\)[\s\S]*$/, "").replace(
      /\/\*[\s\S]*?\*\//g,
      "",
    );
    expect(outside).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    for (const m of outside.matchAll(/(?:color|background|border(?:-color)?):\s*([^;]+);/g))
      expect(m[1]).toMatch(/var\(--|transparent|calc\(/);
  });

  it("the side legend names both sides in text, by column and by price", () => {
    render(<SideLegend />);
    const legend = screen.getByRole("list", { name: "Book sides" });
    expect(legend.textContent).toMatch(/Bid: resting buy liquidity, left column/);
    expect(legend.textContent).toMatch(/Ask: resting sell liquidity, right column/);
  });

  it("a book side reads as its word", () => {
    expect(mount(<SideMark side="bid" />).textContent).toBe("Bid");
    expect(mount(<SideMark side="sell" />).textContent).toBe("▼ Sell");
  });
});

describe("faults and the tree (record minors, C-14.1)", () => {
  it("one bad field draws a dash; the cell and the value still render (no RangeError)", () => {
    expect(mount(<SignedValue value="1e3" />).textContent).toBe("—");
    expect(mount(<SignedValue value="x" />).querySelector("[aria-hidden='true']")).toBeNull();
    const cell = mount(
      <FootprintCellContent
        cell={{ price: "1", bid: "-2", ask: "1e3", delta: "NaN", imbalance: "bid" }}
      />,
    );
    expect(cell.textContent).toBe("— × ——◢Bid imbalance");
  });

  it("every mark has no serious or critical axe violation", async () => {
    // axe probes icon ligatures on a canvas jsdom lacks; without one it skips the probe.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const { container } = render(
      <main>
        <SideLegend />
        <p>
          <SignedValue value="8" /> <SignedValue value="-8" /> <SignedValue value="0" />{" "}
          <SignedValue value="bad" />
        </p>
        <p>
          <ImbalanceMark side="bid" /> <ImbalanceMark side="ask" />
        </p>
        <p>
          <SideMark side="bid" /> <SideMark side="ask" /> <SideMark side="buy" />{" "}
          <SideMark side="sell" />
        </p>
        <p>
          <FootprintCellContent
            cell={{ price: "1", bid: "2", ask: "10", delta: "8", imbalance: "ask" }}
          />
        </p>
      </main>,
    );
    const res = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => v.id)).toEqual([]);
    vi.restoreAllMocks();
  });
});
