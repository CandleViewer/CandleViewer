// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { describe, it, vi } from "vitest";
import { expect, userEvent, within } from "storybook/test";
import { GatedAnnounceProvider, PAGINATION_COPY, Pagination } from "../src/components/index.js";
import * as stories from "../src/components/Pagination.stories.js";
import { seriousViolations } from "./axe.js";
import { holdEnter } from "./heldEnter.js";
import { mount } from "./theme/mount.js";

/** E42-D04 §14's keys, as SCR-135 hands them over: `admin.newest`, `admin.oldest` (`audit.end`), `admin.rate_limited`. */
const NEWEST = "Already at the start of the list.";
const OLDEST = "No older entries.";
const LIMITED = "Paused by a rate limit.";

const handlers = (): { onNewest: () => void; onNewer: () => void; onOlder: () => void } => ({
  onNewest: vi.fn(),
  onNewer: vi.fn(),
  onOlder: vi.fn(),
});

const nav = (host: HTMLElement): HTMLElement =>
  within(host).getByRole("navigation", { name: "Pagination" });
const buttons = (host: HTMLElement): HTMLElement[] => within(nav(host)).getAllByRole("button");
const describedBy = (el: HTMLElement): string[] =>
  (el.getAttribute("aria-describedby") ?? "").split(" ").filter((id) => id !== "");
const text = (id: string): string => document.getElementById(id)?.textContent ?? "";

describe("Pagination (CMP-053), cursor mode", () => {
  it("is a nav named Pagination holding Newest, Newer and Older, in that order, with no current page", async () => {
    const host = await mount(<Pagination {...handlers()} />);
    const root = host.querySelector<HTMLElement>('[data-cmp="CMP-053"]');
    expect(root).toBe(nav(host));
    expect(root?.dataset["mode"]).toBe("cursor");
    expect(buttons(host).map((b) => b.textContent)).toEqual(["Newest", "Newer", "Older"]);
    expect(host.querySelector("[aria-current]")).toBeNull();
    // No page number and no total: a keyset list has neither (E42-D04 D4).
    expect(nav(host).textContent).not.toMatch(/\d/);
  });

  it("asks for each page by its button, once per press", async () => {
    const calls = handlers();
    const host = await mount(<Pagination {...calls} />);
    const [newest, newer, older] = buttons(host);
    await userEvent.click(newest as HTMLElement);
    await userEvent.click(newer as HTMLElement);
    await userEvent.click(older as HTMLElement);
    await userEvent.click(older as HTMLElement);
    expect(calls.onNewest).toHaveBeenCalledTimes(1);
    expect(calls.onNewer).toHaveBeenCalledTimes(1);
    expect(calls.onOlder).toHaveBeenCalledTimes(2);
  });

  it("ignores a held key's repeats: one page per press (E42-D04 §12)", async () => {
    const calls = handlers();
    const host = await mount(<Pagination {...calls} />);
    holdEnter(buttons(host)[2] as HTMLElement, 4);
    expect(calls.onOlder).toHaveBeenCalledTimes(1);
  });

  it("page 1: Newest and Newer are T2 behind one inline reason; Older stays enabled", async () => {
    const calls = handlers();
    const announce = vi.fn();
    const host = await mount(
      <GatedAnnounceProvider announce={announce}>
        <Pagination {...calls} newerReason={NEWEST} />
      </GatedAnnounceProvider>,
    );
    const [newest, newer, older] = buttons(host) as [HTMLElement, HTMLElement, HTMLElement];
    for (const [button, label] of [
      [newest, "Newest"],
      [newer, "Newer"],
    ] as const) {
      expect(button).toHaveAccessibleName(`Not available ${label}`);
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(button).not.toBeDisabled();
      expect(describedBy(button)).toHaveLength(1);
      expect(text(describedBy(button)[0] ?? "")).toBe(NEWEST);
    }
    // One notice, many pointers: the sentence shows once, visibly, inside the pager.
    expect(describedBy(newest)).toEqual(describedBy(newer));
    expect(within(nav(host)).getAllByText(NEWEST)).toHaveLength(1);
    expect(within(nav(host)).getByText(NEWEST)).toBeVisible();
    expect(older).toHaveAccessibleName("Older");
    expect(older).not.toHaveAttribute("aria-disabled");
    await userEvent.click(newer);
    expect(calls.onNewer).not.toHaveBeenCalled();
    expect(announce.mock.calls).toEqual([[NEWEST]]);
  });

  it("the end: Older is T2, described by the host's audit.end line, with no copy of its own", async () => {
    const host = await mount(
      <>
        <p id="audit-end">{OLDEST}</p>
        <Pagination {...handlers()} olderReason={OLDEST} olderReasonId="audit-end" />
      </>,
    );
    const older = buttons(host)[2] as HTMLElement;
    expect(older).toHaveAccessibleName("Not available Older");
    expect(describedBy(older)).toEqual(["audit-end"]);
    expect(within(host).getAllByText(OLDEST)).toHaveLength(1);
  });

  it("a single page: each direction keeps its own reason (one reason per control)", async () => {
    const host = await mount(
      <Pagination {...handlers()} newerReason={NEWEST} olderReason={OLDEST} />,
    );
    const [newest, newer, older] = buttons(host) as [HTMLElement, HTMLElement, HTMLElement];
    expect(text(describedBy(newest)[0] ?? "")).toBe(NEWEST);
    expect(text(describedBy(newer)[0] ?? "")).toBe(NEWEST);
    expect(text(describedBy(older)[0] ?? "")).toBe(OLDEST);
    expect(within(nav(host)).getByText(OLDEST)).toBeVisible();
  });

  it("rate-limited: every button T2 with the blocked reason in place of its own, pointing at the host's notice", async () => {
    const calls = handlers();
    const host = await mount(
      <>
        <p id="limited">{LIMITED}</p>
        <Pagination
          {...calls}
          newerReason={NEWEST}
          blockedReason={LIMITED}
          blockedReasonId="limited"
        />
      </>,
    );
    for (const button of buttons(host)) {
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(describedBy(button)).toEqual(["limited"]);
      await userEvent.click(button);
    }
    expect(within(host).queryByText(NEWEST)).toBeNull();
    expect(within(host).getAllByText(LIMITED)).toHaveLength(1);
    expect(calls.onNewest).not.toHaveBeenCalled();
    expect(calls.onNewer).not.toHaveBeenCalled();
    expect(calls.onOlder).not.toHaveBeenCalled();
  });

  it("rate-limited without the host's notice: one inline line that every button points at", async () => {
    const host = await mount(<Pagination {...handlers()} blockedReason={LIMITED} />);
    const ids = buttons(host).map((button) => describedBy(button));
    expect(new Set(ids.flat()).size).toBe(1);
    expect(within(nav(host)).getAllByText(LIMITED)).toHaveLength(1);
  });

  it("a blank reason is no reason: the button stays enabled", async () => {
    const host = await mount(<Pagination {...handlers()} newerReason="  " />);
    expect(buttons(host)[0]).not.toHaveAttribute("aria-disabled");
  });

  it("takes the host's labels (labels.page.*), the defaults being E42-D04 §14's", async () => {
    expect(PAGINATION_COPY).toEqual({
      nav: "Pagination",
      newest: "Newest",
      newer: "Newer",
      older: "Older",
    });
    const host = await mount(
      <Pagination {...handlers()} labels={{ newest: "Latest", nav: "Audit pages" }} />,
    );
    expect(within(host).getByRole("navigation", { name: "Audit pages" })).toBeVisible();
    expect(within(host).getByRole("button", { name: "Latest" })).toBeVisible();
  });

  it("is a Tab stop per button, a T2 one included, and no live region of its own", async () => {
    const host = await mount(<Pagination {...handlers()} newerReason={NEWEST} />);
    for (const button of buttons(host)) {
      await userEvent.tab();
      expect(button).toHaveFocus();
    }
    expect(nav(host).querySelector("[aria-live], [role='status'], [role='alert']")).toBeNull();
  });

  it("has no serious or critical axe violation, enabled or gated", async () => {
    const host = await mount(
      <>
        <Pagination {...handlers()} />
        <Pagination {...handlers()} newerReason={NEWEST} olderReason={OLDEST} />
      </>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("Pagination stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders one pager", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelectorAll('[data-cmp="CMP-053"]')).toHaveLength(1);
  });

  // The storybook project runs each play in Chromium; here in jsdom too, so a wrong name fails without a browser.
  it("runs each story's play function", { timeout: 20_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    }
  });
});
