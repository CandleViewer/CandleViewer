import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { CopyButton } from "./CopyButton.js";

/** A stand-in value: stories never hold a real secret. */
const VALUE = "ord-7f3a-demo-0001";
const writeText = fn<(text: string) => Promise<void>>();

/**
 * Swaps `navigator.clipboard` for a mock, so no story touches the real clipboard (or waits on a permission
 * prompt). `refuse` makes the write reject, as a denied permission does (E20).
 */
const mockClipboard =
  (refuse = false) =>
  (): (() => void) => {
    writeText.mockReset();
    writeText.mockImplementation(() =>
      refuse ? Promise.reject(new DOMException("denied", "NotAllowedError")) : Promise.resolve(),
    );
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    return () => {
      Reflect.deleteProperty(navigator, "clipboard");
    };
  };

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof CopyButton> = {
  title: "Atoms/CopyButton",
  component: CopyButton,
  args: { value: VALUE, label: "Copy order ID", onCopied: fn() },
  beforeEach: mockClipboard(),
};
export default meta;
type Story = StoryObj<typeof CopyButton>;

const row = { display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" } as const;
const button = (canvas: HTMLElement): HTMLElement =>
  within(canvas).getByRole("button", { name: "Copy order ID" });

/** The status is mounted empty before the first copy, so its first "Copied" is announced. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("status")).toBeEmptyDOMElement();
  },
};

export const Hover: Story = {
  play: async ({ canvasElement }) => userEvent.hover(button(canvasElement)),
};

/** The nested CMP-002 draws the only ring (conv. 20). */
export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(button(canvasElement)).toHaveFocus();
  },
};

/** After a press: the `check` glyph in success.default and "Copied" in the status; never the value. */
export const CopiedState: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    const status = within(canvasElement).getByRole("status");
    await waitFor(() => expect(status).toHaveTextContent("Copied"));
    await expect(writeText).toHaveBeenCalledWith(VALUE);
    await expect(args.onCopied).toHaveBeenCalledTimes(1);
    await expect(button(canvasElement)).toHaveFocus();
    await expect(canvasElement.innerHTML).not.toContain(VALUE);
  },
};

/** E20: the clipboard refused; the `error` glyph and "Copy failed", never the value. */
export const Failed: Story = {
  beforeEach: mockClipboard(true),
  play: async ({ canvasElement, args }) => {
    await userEvent.click(button(canvasElement));
    const status = within(canvasElement).getByRole("status");
    await waitFor(() => expect(status).toHaveTextContent("Copy failed"));
    await expect(args.onCopied).not.toHaveBeenCalled();
    await expect(canvasElement.innerHTML).not.toContain(VALUE);
  },
};

/** Plain disabled, dimmed by the nested CMP-002 only; never gated (E21). */
export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    await expect(button(canvasElement)).toBeDisabled();
    await userEvent.tab();
    await expect(document.body).toHaveFocus();
  },
};

/** A long value changes nothing: the box never grows, the value is never shown. */
export const LongText: Story = {
  args: {
    value: "x".repeat(4096),
    label: "Copy the full audit record identifier and its hash chain",
  },
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByRole("button").getBoundingClientRect();
    await expect(box.width).toBe(box.height);
  },
};

/** Every state under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async ({ canvasElement }) => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    const [first] = within(canvasElement).getAllByRole("button", { name: "Copy order ID" });
    if (first !== undefined) await userEvent.click(first);
    await waitFor(() =>
      expect(within(canvasElement).getAllByRole("status")[0]).toHaveTextContent("Copied"),
    );
  },
  render: (args) => (
    <div style={row}>
      <CopyButton {...args} />
      <CopyButton {...args} />
      <CopyButton {...args} disabled />
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
