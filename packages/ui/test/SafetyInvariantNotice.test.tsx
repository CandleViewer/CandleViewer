// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { SafetyInvariantNotice } from "../src/components/index.js";
import * as stories from "../src/components/SafetyInvariantNotice.stories.js";
import { seriousViolations } from "./axe.js";
import { find, loadCss } from "./css-contract.js";
import { mount } from "./theme/mount.js";

/** E36-D05 FS-1 and FS-2, the rule editors' two sentences, verbatim. */
const LEAD = "Every position keeps a native stop — you can move it, not delete it.";
const CLAUSE =
  "Rules can tighten it, never remove it — the stop is held by the exchange, not by this app.";

const notice = (): Promise<HTMLElement> =>
  mount(<SafetyInvariantNotice lead={LEAD} clause={CLAUSE} />);

describe("SafetyInvariantNotice (CMP-158), the rule editors' variant", () => {
  it("is one note: CMP-028's info callout carrying the two sentences byte for byte", async () => {
    const host = await notice();
    expect(host.querySelectorAll('[data-cmp="CMP-158"]')).toHaveLength(1);
    const note = within(host).getByRole("note");
    expect(note.textContent).toBe(`${LEAD} ${CLAUSE}`);
    expect(note.querySelector('.cv-callout[data-cmp="CMP-028"]')?.getAttribute("data-tone")).toBe(
      "info",
    );
    expect(await seriousViolations(host)).toEqual([]);
  });

  it("is never a live region: no aria-live, no status or alert, and the words are there at mount", async () => {
    const host = await notice();
    expect(host.querySelector("[aria-live]")).toBeNull();
    expect([within(host).queryByRole("status"), within(host).queryByRole("alert")]).toEqual([
      null,
      null,
    ]);
    expect(within(host).getByRole("note")).toHaveTextContent(LEAD);
  });

  it("has no dismiss control and nothing in the Tab order; its glyph is hidden from assistive technology", async () => {
    const host = await notice();
    expect(within(host).queryAllByRole("button")).toEqual([]);
    expect(host.querySelectorAll("button, a, input, [tabindex]")).toHaveLength(0);
    const glyph = host.querySelector(".cv-callout__glyph svg");
    expect(glyph?.getAttribute("aria-hidden")).toBe("true");
  });

  it("renders the host's own key: each variant's sentences are its props", async () => {
    const host = await mount(
      <SafetyInvariantNotice lead={LEAD} clause="It is placed with the order, not after it." />,
    );
    expect(within(host).getByRole("note").textContent).toBe(
      `${LEAD} It is placed with the order, not after it.`,
    );
  });
});

describe("safetynotice.css: CMP-158's look over callout.css", () => {
  const notes = loadCss("safetynotice.css");
  const callout = loadCss("callout.css");
  const both = ".cv-safety-notice .cv-callout__title";

  it("never moves: no transition or animation here or in CMP-028, in either motion mode (E32-D06 §8)", () => {
    for (const css of [notes, callout]) expect(css.all).not.toMatch(/transition|animation/);
  });

  it("reads both sentences in color.text.primary: caption in compact, body in comfortable; tokens only", () => {
    const base = find(notes.normal, both, "color");
    expect(base).toContain("color: var(--color-text-primary)");
    expect(base).toContain("var(--type-ui-caption-font-size)");
    expect(find(notes.normal, ".cv-safety-notice .cv-callout__body", "color")).toBe(base);
    expect(find(notes.normal, `[data-density="comfortable"] ${both}`, "font")).toContain(
      "var(--type-ui-body-font-size)",
    );
    expect(notes.normal).not.toMatch(
      /#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(|\d+px|--color-text-secondary/i,
    );
  });

  it("forced colours: the words in CanvasText, as CMP-028's glyph and edge are", () => {
    expect(find(notes.forced, both, "color")).toContain("color: CanvasText");
    expect(find(callout.forced, ".cv-callout__glyph", "color")).toContain("color: CanvasText");
    expect(notes.forced).not.toMatch(/var\(--/);
  });
});

it("runs each catalogued story's play function", async () => {
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    const canvasElement = document.body.appendChild(document.createElement("div"));
    await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
  }
});
