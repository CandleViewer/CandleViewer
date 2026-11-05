/**
 * E42-S08 (#1137) §4.4: the drawing (BQ-6 as ruled: a plain SVG drawing for now; E42-D05 §11 SI-4,
 * D35), on the frozen B01 (`frozenCharts.ts`). A labelled region holding one image, named by its
 * `aria-label` (no `<title>`), its details the text list (`aria-details`); the current states are
 * exactly the caller's, each with a 3 px border, a bold label and the word "current"; a final
 * state has its second border; the region is a Tab stop only while it scrolls, measured as it
 * resizes; text is SVG text, never markup; a chart over the bounds draws nothing.
 */
import { createRequire } from "node:module";
import { act, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChartDiagram } from "../../../../src/features/admin/statecharts/ChartDiagram";
import { ChartTextList } from "../../../../src/features/admin/statecharts/ChartTextList";
import {
  currentIds,
  vetStately,
  type ChartModel,
} from "../../../../src/features/admin/statecharts/chartModel";
import { frozenChart, type FrozenChart } from "./frozenCharts";

// axe-core is a transitive dependency of @axe-core/playwright (as in AdminArea.test.tsx).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const HASH = "e".repeat(64);
function modelOf(name: FrozenChart, kind: string): ChartModel {
  const model = vetStately(frozenChart(name), kind, HASH);
  if (model === null) throw new Error(`${name}: refused`);
  return model;
}
const B01 = modelOf("B01.order", "order");
/** `latched_machine.py`'s configuration (SC-CHAIN-TRIPS): triggered, its stop-loss present. */
const LATCHED = currentIds(B01, [
  "order",
  "order.lifecycle",
  "order.lifecycle.triggered",
  "order.protection",
  "order.protection.sl_present",
]);
const NONE: ReadonlySet<string> = new Set();

function draw(model: ChartModel = B01, current: ReadonlySet<string> = NONE) {
  return render(
    <>
      <ChartDiagram model={model} current={current} listId="chart-list" />
      <ChartTextList model={model} current={current} id="chart-list" />
    </>,
  );
}

/** The drawn boxes' labels marked current, from the SVG's own data. */
const currentLabels = (svg: Element): string[] =>
  [...svg.querySelectorAll("rect[data-current]")].map(
    (rect) => rect.parentElement?.querySelector("text")?.textContent ?? "",
  );

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the drawing of B01 order", () => {
  it("test_diagram_is_a_named_region_with_one_image_detailed_by_the_text_list", () => {
    draw();
    const region = screen.getByRole("region", { name: "State diagram: order (B1)" });
    const image = within(region).getByRole("img");
    expect(image).toHaveAccessibleName(
      "order (B1) chart: 23 states. The list after it gives every state and transition.",
    );
    // Named by `aria-label` alone: no `<title>`, which a browser reads as its description too.
    expect(image).toHaveAttribute(
      "aria-label",
      "order (B1) chart: 23 states. The list after it gives every state and transition.",
    );
    expect(image.querySelector("title")).toBeNull();
    // A relationship, never read out: the list follows in the DOM, whole (A-1137-10).
    expect(image).toHaveAttribute("aria-details", "chart-list");
    expect(image).not.toHaveAttribute("aria-describedby");
    expect(image).toHaveAccessibleDescription("");
    expect(document.getElementById("chart-list")).toHaveTextContent(/^States/);
  });

  it("test_diagram_draws_every_state_once_and_its_two_regions_dashed", () => {
    draw();
    const svg = screen.getByRole("img");
    const labels = [...svg.querySelectorAll("text")].map((t) => t.textContent);
    for (const state of B01.states) expect(labels, state.id).toContain(state.label);
    expect(svg.querySelectorAll("rect.cv-inspector-diagram__group[data-region]")).toHaveLength(2);
    // five final states, each with its second border
    expect(svg.querySelectorAll("rect.cv-inspector-diagram__final")).toHaveLength(5);
    expect(svg.querySelectorAll("circle")).toHaveLength(2); // one initial dot per region
  });

  it("test_diagram_marks_the_configurations_leaves_current_in_words_and_border", () => {
    draw(B01, LATCHED);
    const svg = screen.getByRole("img");
    expect(currentLabels(svg)).toEqual(["triggered", "sl_present"]);
    const words = [...svg.querySelectorAll("text.cv-inspector-diagram__current")];
    expect(words.map((w) => w.textContent)).toEqual(["current", "current"]);
    const bold = [...svg.querySelectorAll("text.cv-inspector-diagram__label[data-current]")];
    expect(bold.map((t) => t.textContent)).toEqual(["triggered", "sl_present"]);
  });

  it("test_diagram_marks_nothing_current_when_none_is_given", () => {
    draw(B01, NONE);
    const svg = screen.getByRole("img");
    expect(svg.querySelectorAll("[data-current]")).toHaveLength(0);
    expect(svg.textContent).not.toContain("current");
  });

  it("test_diagram_text_is_svg_text_and_every_arrow_has_its_head", () => {
    draw();
    const svg = screen.getByRole("img");
    const marker = svg.querySelector("marker");
    expect(marker?.id).toMatch(/^cv-inspector-arrow-[A-Za-z0-9_-]+$/);
    const edges = [...svg.querySelectorAll("path.cv-inspector-diagram__edge")];
    expect(edges.length).toBe(76 + 2); // the pairs and the two initial arrows
    for (const edge of edges) expect(edge.getAttribute("marker-end")).toBe(`url(#${marker?.id})`);
    expect(svg.querySelector("foreignObject")).toBeNull();
  });
});

describe("the region's Tab stop and the bounds", () => {
  it("test_diagram_region_is_no_tab_stop_while_it_does_not_scroll", () => {
    draw();
    expect(screen.getByRole("region", { name: /^State diagram/ })).not.toHaveAttribute("tabindex");
  });

  it("test_diagram_region_takes_a_tab_stop_while_it_scrolls", () => {
    vi.stubGlobal("ResizeObserver", undefined); // measured once, on mount
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(900);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(400);
    draw();
    expect(screen.getByRole("region", { name: /^State diagram/ })).toHaveAttribute("tabindex", "0");
  });

  it("test_diagram_region_measures_as_it_resizes_and_stops_measuring_on_unmount", () => {
    // ResizeObserver's path: the region and its drawing are observed; a resize that makes the
    // region scroll gives it its Tab stop, and one that ends the scroll takes the stop away.
    const observed: Element[] = [];
    const stopped = vi.fn();
    let resized: (() => void) | undefined;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          resized = callback;
        }
        observe(node: Element): void {
          observed.push(node);
        }
        disconnect(): void {
          stopped();
        }
      },
    );
    let wide = 400;
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(() => wide);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(400);
    const view = draw();
    const region = screen.getByRole("region", { name: /^State diagram/ });
    expect(observed).toEqual([region, region.querySelector("svg")]);
    expect(region).not.toHaveAttribute("tabindex");
    wide = 900;
    act(() => resized?.());
    expect(region).toHaveAttribute("tabindex", "0");
    wide = 400;
    act(() => resized?.());
    expect(region).not.toHaveAttribute("tabindex");
    view.unmount();
    expect(stopped).toHaveBeenCalledTimes(1);
  });

  it("test_diagram_draws_nothing_for_a_chart_over_the_bounds", () => {
    const states = Object.fromEntries(Array.from({ length: 41 }, (_, i) => [`s${i}`, {}]));
    const big = vetStately({ id: "big", initial: "s0", states }, "big", HASH);
    if (big === null) throw new Error("refused");
    const { container } = render(<ChartDiagram model={big} current={NONE} listId="x" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("axe", () => {
  it.each(["dark", "light"])("test_diagram_has_no_serious_axe_violation_in_%s", async (theme) => {
    document.documentElement.setAttribute("data-theme", theme);
    draw(B01, LATCHED);
    // jsdom has no layout: contrast is the real-browser collectors' and inspector-pairs' (SVG).
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    document.documentElement.removeAttribute("data-theme");
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});
