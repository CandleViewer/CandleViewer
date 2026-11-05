import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { Pagination, type PaginationProps } from "./Pagination.js";

/** E42-D04 §14's strings, as SCR-135 hands them to the pager. */
const NEWEST = "Already at the start of the list.";
const END = "No older entries.";
const LIMITED = "Paused by a rate limit.";
const LIMITED_LINE =
  "Too many requests — try again at 14:03:12 UTC (in 45 s). Run tamper check and opening records still work.";

type Host = PaginationProps & {
  /** SCR-135's `audit.end` line under the last row, the node Older's reason points at (AL-9). */
  readonly endLine?: boolean;
  /** SCR-135's `audit.limited` line and its one notice under the page header (AL-16). */
  readonly limitedLine?: boolean;
};

/** The pager under the grid in SCR-135's content column at 1280 (E42-D03 D1, 944 px), with the host's lines. */
function Pager({ endLine = false, limitedLine = false, ...props }: Host): JSX.Element {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-stack-sm)",
        maxWidth: "59rem",
        color: "var(--color-text-primary)",
        font: "var(--type-ui-body-font-weight) var(--type-ui-body-font-size) / var(--type-ui-body-line-height) var(--type-ui-body-font-family)",
      }}
    >
      {limitedLine ? (
        <p style={{ margin: 0 }}>
          {LIMITED_LINE} <span id="audit-limited">{LIMITED}</span>
        </p>
      ) : null}
      {endLine ? (
        <p id="audit-end" style={{ margin: 0, color: "var(--color-text-secondary)" }}>
          {END}
        </p>
      ) : null}
      <Pagination {...props} />
    </div>
  );
}

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Pager> = {
  title: "Molecules/Pagination",
  component: Pager,
  args: { onNewest: fn(), onNewer: fn(), onOlder: fn() },
};
export default meta;
type Story = StoryObj<typeof Pager>;

const pager = (canvas: HTMLElement): HTMLElement =>
  within(canvas).getByRole("navigation", { name: "Pagination" });
const descriptionOf = (el: HTMLElement): string =>
  document.getElementById(el.getAttribute("aria-describedby") ?? "")?.textContent ?? "";

/** A keyset page inside the list: Newest, Newer and Older all enabled, no page number, no current page. */
export const CursorMode: Story = {
  // Each story asserting on its handlers takes its own, so no other story's presses count.
  args: { onNewest: fn(), onNewer: fn(), onOlder: fn() },
  play: async ({ canvasElement, args }) => {
    const buttons = within(pager(canvasElement)).getAllByRole("button");
    await expect(buttons.map((b) => b.textContent)).toEqual(["Newest", "Newer", "Older"]);
    await expect(canvasElement.querySelector("[aria-current]")).toBeNull();
    await userEvent.click(buttons[2] as HTMLElement);
    await expect(args.onOlder).toHaveBeenCalledTimes(1);
  },
};

/**
 * The list's ends (AL-2, AL-9): on page 1 Newest and Newer are T2 `admin.newest`, its reason under the pager; at
 * `has_more: false` Older is T2 `admin.oldest`, whose node is the host's `audit.end` line.
 */
export const CursorKeyset: Story = {
  args: {
    onNewest: fn(),
    onNewer: fn(),
    onOlder: fn(),
    newerReason: NEWEST,
    olderReason: END,
    olderReasonId: "audit-end",
    endLine: true,
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(pager(canvasElement));
    const newest = canvas.getByRole("button", { name: "Not available Newest" });
    const older = canvas.getByRole("button", { name: "Not available Older" });
    await expect(descriptionOf(newest)).toBe(NEWEST);
    await expect(older).toHaveAttribute("aria-describedby", "audit-end");
    await expect(canvas.getByText(NEWEST)).toBeVisible();
    await userEvent.click(older);
    await expect(args.onOlder).not.toHaveBeenCalled();
  },
};

/** AL-16: a `429` makes every button T2 `admin.rate_limited`, pointing at the one notice beside SCR-158's line. */
export const RateLimited: Story = {
  args: {
    newerReason: NEWEST,
    blockedReason: LIMITED,
    blockedReasonId: "audit-limited",
    limitedLine: true,
  },
  play: async ({ canvasElement }) => {
    for (const button of within(pager(canvasElement)).getAllByRole("button")) {
      await expect(button).toHaveAttribute("aria-disabled", "true");
      await expect(button).toHaveAttribute("aria-describedby", "audit-limited");
    }
    await expect(within(canvasElement).queryByText(NEWEST)).toBeNull();
    await userEvent.tab();
    await expect(
      within(pager(canvasElement)).getByRole("button", { name: /Newest$/ }),
    ).toHaveFocus();
  },
};
