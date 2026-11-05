import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
import { CopyableCodeBlock } from "./CopyableCodeBlock.js";

/**
 * E42-D04's worked example as SCR-136's raw record shows it: the entry as served, its `detail` already redacted by
 * the server. The hashes are stand-ins: a story never holds a real value.
 */
const RECORD = JSON.stringify(
  {
    id: 1204118,
    ts: "2026-10-22T14:01:50.212000+00:00",
    actor_user_id: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002",
    actor_username: "alex",
    action: "orders.submit",
    subject_type: "order",
    subject_id: "0c000000-0000-4000-8000-000000000001",
    subject_label: "BTCUSDT",
    outcome: "success",
    severity: "info",
    reason: "validated",
    environment: "live",
    request_id: "0193f2bb-9c11-7a3d-88f1-0d2e3f4a5b6c",
    detail: {
      before: null,
      after: { symbol: "BTCUSDT", side: "buy", qty: "0.250", price: "64010.0" },
    },
    entry_hash: "3c9a5e2f1b",
    prev_hash: "7d1e0b44aa",
  },
  null,
  2,
);

/** A rule's IR export (CMP-068's other host): YAML, shown as given. */
const RULE = `rule: breakout_long
version: 3
when:
  all:
    - price_crosses_above: { level: 64000.0 }
    - cvd_slope_positive: { window: 5m }
then:
  - alert: { channel: desktop }
`;

/** Every entry of a page, pretty-printed: much taller than the drawer's region, so it scrolls. */
const LONG = JSON.stringify(
  Array.from({ length: 24 }, (_, i) => ({
    id: 1204118 - i,
    action: i % 3 === 0 ? "flags.change" : "admin.area_entered",
    outcome: "success",
    detail: { before: null, after: { route: "/admin/audit", reauth_age_s: 412 + i } },
  })),
  null,
  2,
);

const writeText = fn<(text: string) => Promise<void>>();

/** Swaps `navigator.clipboard` for a mock, so no story touches the real clipboard. */
const mockClipboard = (): (() => void) => {
  writeText.mockReset();
  writeText.mockImplementation(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  return () => {
    Reflect.deleteProperty(navigator, "clipboard");
  };
};

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof CopyableCodeBlock> = {
  title: "Molecules/CopyableCodeBlock",
  component: CopyableCodeBlock,
  args: { code: RECORD, language: "json", label: "Raw record" },
  beforeEach: mockClipboard,
  decorators: [
    (Story) => (
      // SCR-136's drawer body at 1280 (E42-D04 D1: 480 px, less its insets).
      <div style={{ maxWidth: "27rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof CopyableCodeBlock>;

const region = (canvas: HTMLElement, name: string): HTMLElement =>
  within(canvas).getByRole("region", { name });

/** SCR-136's raw record (AD-2): the entry as served, then its Copy, which copies it exactly. */
export const Json: Story = {
  name: "JSON",
  play: async ({ canvasElement }) => {
    const pre = region(canvasElement, "Raw record");
    await expect(pre).toHaveAttribute("tabindex", "0");
    await expect(pre).toHaveTextContent('"action": "orders.submit"');
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Copy Raw record" }));
    await expect(writeText).toHaveBeenCalledWith(RECORD);
  },
};

/** YAML, shown as given: the block names the format and never parses it. */
export const Yaml: Story = {
  name: "YAML",
  args: { code: RULE, language: "yaml", label: "Rule export", copyLabel: "Copy the rule export" },
  play: async ({ canvasElement }) => {
    await expect(region(canvasElement, "Rule export")).toHaveTextContent("rule: breakout_long");
    await expect(canvasElement.querySelector('[data-cmp="CMP-068"]')).toHaveAttribute(
      "data-language",
      "yaml",
    );
    await expect(
      within(canvasElement).getByRole("button", { name: "Copy the rule export" }),
    ).toBeVisible();
  },
};

/** Taller than its cap: the region scrolls inside it and is a Tab stop of its own (WCAG 2.1.1). */
export const LongScrollable: Story = {
  args: { code: LONG, maxHeight: "12rem" },
  play: async ({ canvasElement }) => {
    const pre = region(canvasElement, "Raw record");
    await userEvent.tab();
    await expect(pre).toHaveFocus();
    // Laid out (a browser), the text overflows the cap; jsdom lays nothing out.
    if (pre.clientHeight > 0) await expect(pre.scrollHeight).toBeGreaterThan(pre.clientHeight);
  },
};
