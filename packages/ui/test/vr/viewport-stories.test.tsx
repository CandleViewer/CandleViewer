// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { LongText } from "../../src/components/Drawer.stories.js";
import { Scrolling } from "../../src/components/Menu.stories.js";

/** The capture's viewport height: the brief's 1920x1080 primary target (config.test.ts pins `CONTEXT`). */
const VIEWPORT_HEIGHT = 1080;

/** A primitive token's value, from the token source (DTCG, flat dotted names). */
const TOKENS = JSON.parse(
  readFileSync(resolve(import.meta.dirname, "../../tokens/primitives.tokens.json"), "utf-8"),
) as Record<string, { $value: string } | undefined>;
const token = (name: string): number => Number(TOKENS[name]?.$value);

describe("a story whose state depends on the viewport", () => {
  it("Menu Scrolling has more rows than a 1080 px viewport holds at the compact row height", () => {
    const story = Scrolling.render?.({}, {} as never) as ReactElement<{ items: unknown[] }>;
    const rows = story.props.items.length;
    // Fewer rows fit under the trigger at 1080 px: the menu never caps its height, so it cannot scroll.
    expect(rows * token("size.row.compact")).toBeGreaterThan(VIEWPORT_HEIGHT);
  });

  it("Drawer LongText has more lines than a 1080 px drawer holds, even when no paragraph wraps", () => {
    const story = LongText.render?.({}, {} as never) as ReactElement<{ children: unknown[] }>;
    const paragraphs = story.props.children.length;
    // At 1920 px the drawer is 480 px wide and a paragraph fits one line: the body must still scroll,
    // or it never becomes the readable group the play looks for.
    const line = token("font.size.base") * token("font.lineheight.normal");
    expect(paragraphs * line).toBeGreaterThan(VIEWPORT_HEIGHT);
  });
});
