// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act } from "react";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { CopyableCodeBlock } from "../src/components/index.js";
import * as stories from "../src/components/CopyableCodeBlock.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

/** E42-D04's worked example, as SCR-136's raw record shows it: the entry as served, `detail` already redacted. */
const RAW = JSON.stringify(
  {
    id: 1204118,
    ts: "2026-10-22T14:01:50.212000+00:00",
    action: "orders.submit",
    outcome: "success",
    detail: { before: null, after: { symbol: "BTCUSDT", side: "buy" } },
  },
  null,
  2,
);

const writeText = vi.fn<(text: string) => Promise<void>>();

beforeEach(() => {
  writeText.mockReset();
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
});

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
});

const region = (host: HTMLElement): HTMLElement =>
  within(host).getByRole("region", { name: "Raw record" });

describe("CopyableCodeBlock (CMP-068)", () => {
  it("is a pre that is a focusable scroll region named by its label, the code inside as served", async () => {
    const host = await mount(<CopyableCodeBlock code={RAW} language="json" label="Raw record" />);
    const pre = region(host);
    expect(pre.tagName).toBe("PRE");
    expect(pre).toHaveAttribute("tabindex", "0");
    expect(pre).toHaveClass("cv-focus-ring");
    expect(pre.querySelector("code")?.textContent).toBe(RAW);
    const root = host.querySelector<HTMLElement>('[data-cmp="CMP-068"]');
    expect(root?.dataset["language"]).toBe("json");
    await userEvent.tab();
    expect(pre).toHaveFocus();
  });

  it("follows the region with its Copy (CMP-033), named after the label, which copies the code exactly", async () => {
    const host = await mount(<CopyableCodeBlock code={RAW} language="json" label="Raw record" />);
    const copy = within(host).getByRole("button", { name: "Copy Raw record" });
    // DOM and Tab order: the region, then its Copy (E42-D04 §5 Keys: the <pre> and its Copy).
    expect(region(host).compareDocumentPosition(copy) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    await act(async () => {
      fireEvent.click(copy);
    });
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(RAW);
    expect(within(host).getByRole("status")).toHaveTextContent("Copied");
  });

  it("takes the host's name for the Copy when given one", async () => {
    const host = await mount(
      <CopyableCodeBlock
        code="a: 1"
        language="yaml"
        label="Rule export"
        copyLabel="Copy the rule export"
      />,
    );
    expect(within(host).getByRole("button", { name: "Copy the rule export" })).toBeVisible();
  });

  it("caps the region at the host's maxHeight through a custom property, and sets none without one", async () => {
    const capped = await mount(
      <CopyableCodeBlock code={RAW} language="json" label="Raw record" maxHeight="12rem" />,
    );
    const root = capped.querySelector<HTMLElement>('[data-cmp="CMP-068"]');
    expect(root?.style.getPropertyValue("--cv-codeblock-max-height")).toBe("12rem");
    document.body.replaceChildren();
    const free = await mount(<CopyableCodeBlock code={RAW} language="json" label="Raw record" />);
    expect(free.querySelector<HTMLElement>('[data-cmp="CMP-068"]')?.getAttribute("style")).toBe(
      null,
    );
  });

  it("never interprets the code: markup in it stays text", async () => {
    const host = await mount(
      <CopyableCodeBlock code={'{"label": "<b>bold</b>"}'} language="json" label="Raw record" />,
    );
    expect(region(host).querySelector("b")).toBeNull();
    expect(region(host)).toHaveTextContent('{"label": "<b>bold</b>"}');
  });

  it("speaks only through CMP-033's status: no live region or alert of its own", async () => {
    const host = await mount(<CopyableCodeBlock code={RAW} language="json" label="Raw record" />);
    expect(host.querySelectorAll("[aria-live], [role='alert'], [role='status']")).toHaveLength(1);
    expect(within(host).getByRole("status").closest(".cv-copy-button")).not.toBeNull();
  });

  it("has no serious or critical axe violation", async () => {
    const host = await mount(<CopyableCodeBlock code={RAW} language="json" label="Raw record" />);
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("CopyableCodeBlock stories", () => {
  it.each(Object.entries(composeStories(stories)))(
    "%s renders one named region",
    async (_name, Story) => {
      const host = await mount(<Story />);
      expect(host.querySelectorAll('[data-cmp="CMP-068"]')).toHaveLength(1);
      expect(within(host).getAllByRole("region")).toHaveLength(1);
    },
  );

  // The storybook project runs each play in Chromium; here in jsdom too, so a wrong name fails without a browser.
  it("runs each story's play function", { timeout: 20_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    }
  });
});
