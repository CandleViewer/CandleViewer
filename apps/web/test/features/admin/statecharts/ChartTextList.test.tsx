/**
 * E42-S08 (#1137) §4.2: the chart's text list, the normative non-visual equivalent of the drawing
 * and AC4's oracle (D35, D45). Every state, nested and marked in words, then every transition as
 * "from → to on EVENT" with the arrow hidden and "to" spoken. It marks "(current)" only on the
 * served configuration's leaves, and is never truncated, never scrolled and never live. The golden
 * lists read the frozen B18 and B01 (`frozenCharts.ts`), which no chart bump moves.
 */
import { createRequire } from "node:module";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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

const HASH = "b".repeat(64);

/** A frozen chart's model, as its export serves it. */
function chart(name: FrozenChart, kind: string): ChartModel {
  const model = vetStately(frozenChart(name), kind, HASH);
  if (model === null) throw new Error(`${name}: refused`);
  return model;
}
const B18 = chart("B18.kill_switch", "kill_switch");
const B01 = chart("B01.order", "order");
/** `latched_machine.py`'s configuration (SC-CHAIN-TRIPS). */
const LATCHED = [
  "order",
  "order.lifecycle",
  "order.lifecycle.triggered",
  "order.protection",
  "order.protection.sl_present",
];
const NONE: ReadonlySet<string> = new Set();

/** What assistive technology reads: the text without its `aria-hidden` parts. */
function spoken(node: Element): string {
  const copy = node.cloneNode(true) as Element;
  copy.querySelectorAll('[aria-hidden="true"]').forEach((hidden) => hidden.remove());
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}
/** What the eye reads: the text without its visually hidden parts. */
function seen(node: Element): string {
  const copy = node.cloneNode(true) as Element;
  copy.querySelectorAll(".cv-visually-hidden").forEach((hidden) => hidden.remove());
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}
/** A state item's own words, without its children's list. */
function own(item: Element): string {
  const copy = item.cloneNode(true) as Element;
  copy.querySelectorAll("ul").forEach((list) => list.remove());
  return (copy.textContent ?? "").trim();
}

function renderList(model: ChartModel, current: ReadonlySet<string> = NONE) {
  render(<ChartTextList model={model} current={current} id="chart-text" />);
  const root = document.getElementById("chart-text");
  if (root === null) throw new Error("no text list");
  const states = root.querySelector(":scope > ul");
  if (states === null) throw new Error("no state list");
  const transitions = [...root.querySelectorAll(":scope > div > ul > li")];
  return { root, states, transitions };
}

describe("the text list of B18 kill_switch", () => {
  it("test_text_list_b18_lists_its_six_states_with_their_markers", () => {
    const { states } = renderList(B18);
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "States",
      "Transitions",
    ]);
    expect(
      within(states as HTMLElement)
        .getAllByRole("listitem")
        .map(own),
    ).toEqual([
      "clear (initial)",
      "engaging",
      "cancelling",
      "flattening",
      "engaged",
      "engaged_incomplete",
    ]);
  });

  it("test_text_list_b18_speaks_every_transition_with_to_and_hides_the_arrow", () => {
    const { transitions } = renderList(B18);
    expect(transitions.map(spoken)).toEqual([
      "Any state that doesn't handle it itself to engaged_incomplete on KILL",
      "clear to engaging on ENGAGE",
      "engaging to cancelling (always)",
      "engaging to engaged (always)",
      "cancelling to flattening when cancel_all_working_orders is done",
      "cancelling to engaged when cancel_all_working_orders is done",
      "cancelling to engaged when cancel_all_working_orders fails",
      "flattening to engaged when flatten_all_positions is done",
      "flattening to engaged_incomplete when flatten_all_positions is done",
      "flattening to engaged_incomplete when flatten_all_positions fails",
      "engaged to clear on RELEASE",
      "engaged on RELEASE: no state change",
      "engaged_incomplete to flattening on RETRY_FLATTEN",
      "engaged_incomplete to clear on RELEASE",
      "engaged_incomplete on RELEASE: no state change",
    ]);
    expect(seen(transitions[1] as Element)).toBe("clear → engaging on ENGAGE");
    const arrows = transitions.flatMap((item) => [...item.querySelectorAll("span")]);
    for (const arrow of arrows.filter((span) => span.textContent === "→")) {
      expect(arrow).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("test_text_list_groups_transitions_one_list_per_source_in_chart_order", () => {
    const { root } = renderList(B18);
    const lists = [...root.querySelectorAll(":scope > div > ul")];
    expect(lists.map((list) => list.children.length)).toEqual([1, 1, 2, 3, 3, 2, 3]);
  });
});

describe("the text list of B01 order with a latched configuration", () => {
  const current = currentIds(B01, LATCHED);

  it("test_text_list_b01_nests_its_23_states_under_two_parallel_regions", () => {
    const { root, states } = renderList(B01, current);
    expect(within(root).getByText("The top-level states run in parallel.")).toBeInTheDocument();
    const items = within(states as HTMLElement).getAllByRole("listitem");
    expect(items).toHaveLength(23);
    const regions = [...states.querySelectorAll(":scope > li")];
    expect(regions.map(own)).toEqual(["lifecycle", "protection"]);
    expect(regions.map((region) => region.querySelectorAll(":scope > ul > li").length)).toEqual([
      17, 4,
    ]);
    expect(items.map(own).filter((words) => words.includes("(final)"))).toEqual([
      "filled (final)",
      "cancelled (final)",
      "rejected (final)",
      "expired (final)",
      "killed (final)",
    ]);
  });

  it("test_text_list_marks_current_only_on_the_configurations_leaves", () => {
    const { states } = renderList(B01, current);
    const items = within(states as HTMLElement).getAllByRole("listitem");
    expect(items.map(own).filter((words) => words.includes("(current)"))).toEqual([
      "triggered (current)",
      "sl_present (current)",
    ]);
    // Bold as well as the word: weight is never the only signal.
    const bold = [...states.querySelectorAll("span")].filter((s) => s.style.fontWeight !== "");
    expect(bold.map((span) => span.textContent)).toEqual(["triggered", "sl_present"]);
    expect(items.map(own)).toContain("not_required (initial)");
  });

  it("test_text_list_with_no_current_states_marks_none", () => {
    const { root } = renderList(B01, NONE);
    expect(root.textContent).not.toContain("(current)");
  });

  it("test_text_list_lists_every_transition_once", () => {
    const { transitions } = renderList(B01, current);
    expect(transitions).toHaveLength(B01.edges.length);
    expect(new Set(transitions.map(spoken)).size).toBe(B01.edges.length);
  });
});

describe("the text list's form", () => {
  it("test_text_list_labels_a_shared_name_by_its_path_in_transitions", () => {
    const model = vetStately(
      {
        id: "m",
        type: "parallel",
        on: { RESET: "#m.a.idle" },
        states: {
          a: { initial: "idle", states: { idle: { on: { GO: "#m.b.idle" } } } },
          b: { initial: "idle", states: { idle: { after: { "500": [{}] } } } },
        },
      },
      "m",
      HASH,
    );
    if (model === null) throw new Error("refused");
    const { transitions } = renderList(model);
    expect(transitions.map(spoken)).toEqual([
      "Any state that doesn't handle it itself to a.idle on RESET",
      "a.idle to b.idle on GO",
      "b.idle after 500: no state change",
    ]);
  });

  it("test_text_list_names_its_node_and_takes_a_heading_level", () => {
    render(<ChartTextList model={B18} current={NONE} id="described" headingLevel={4} />);
    expect(document.getElementById("described")).not.toBeNull();
    expect(screen.getAllByRole("heading", { level: 4 })).toHaveLength(2);
    expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(0);
  });

  it("test_text_list_is_never_cut_scrolled_or_live", () => {
    const { root } = renderList(B01, currentIds(B01, LATCHED));
    expect(root.style.overflowWrap).toBe("anywhere");
    for (const node of [root, ...root.querySelectorAll("*")] as HTMLElement[]) {
      expect(node.style.overflow, node.tagName).toBe("");
      expect(node.style.textOverflow, node.tagName).toBe("");
      expect(node.getAttribute("aria-live"), node.tagName).toBeNull();
      expect(node.getAttribute("role"), node.tagName).toBeNull();
    }
  });

  it("test_text_list_has_no_serious_axe_violation", { timeout: 60_000 }, async () => {
    renderList(B01, currentIds(B01, LATCHED));
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});
