import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import type { MenuItem } from "./Menu.js";
import { RbacGate } from "./RbacGate.js";
import { formatRbacReason } from "./rbacReasons.js";
import { SplitButton } from "./SplitButton.js";

/** The Positions row's ▾ items, the deck's words (E29-D02:333–338; board 09). */
const closeItems = (): MenuItem[] => [
  { id: "pct25", label: "Close 25 %", onSelect: fn() },
  { id: "pct50", label: "Close 50 %", onSelect: fn() },
  { id: "custom", label: "Close custom size…", onSelect: fn() },
  { id: "limit", label: "Close at limit…", onSelect: fn() },
  { id: "reverse", label: "Reverse…", onSelect: fn() },
  { id: "sltp", label: "SL/TP…", onSelect: fn() },
  { id: "chart", label: "Chart", onSelect: fn() },
];

/** E29-D05 N-05 (PROPOSED): the ▾ names its row. */
const MORE_CLOSE = "More close actions, BTCUSDT Long on Main";
/** `rbac.permission` with the verb "change positions": the Viewer's reason (E29-D02:433). */
const VIEWER = formatRbacReason("rbac.permission", { verb: "change positions" });
/** `blotter.close_in_flight` (PROPOSED, E29-D03): the ▾ items while a close is in flight (E29-D02:341). */
const IN_FLIGHT = "A close for this position is already in flight.";

const meta: Meta<typeof SplitButton> = {
  title: "Molecules/SplitButton",
  component: SplitButton,
  args: { primary: { label: "Close", onClick: fn() }, menuLabel: MORE_CLOSE },
  render: (args) => <SplitButton {...args} items={closeItems()} />,
};
export default meta;
type Story = StoryObj<typeof SplitButton>;

const primaryOf = (canvas: HTMLElement, name = "Close"): HTMLElement =>
  within(canvas).getByRole("button", { name });
const toggleOf = (canvas: HTMLElement): HTMLElement =>
  within(canvas).getByRole("button", { name: MORE_CLOSE });

/** Two controls: the primary and the ▾, each its own Tab stop (`15` CMP-057). */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(primaryOf(canvasElement)).toHaveFocus();
    await userEvent.tab();
    await expect(toggleOf(canvasElement)).toHaveFocus();
    await expect(toggleOf(canvasElement)).toHaveAttribute("aria-haspopup", "menu");
  },
};

export const Hover: Story = {
  play: async ({ canvasElement }) => userEvent.hover(primaryOf(canvasElement)),
};

export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(primaryOf(canvasElement)).toHaveFocus();
  },
};

/** ↓ on the ▾ opens CMP-041's menu on its first item (board 09). */
export const MenuOpen: Story = {
  play: async ({ canvasElement }) => {
    toggleOf(canvasElement).focus();
    await userEvent.keyboard("{ArrowDown}");
    const page = within(document.body);
    await waitFor(() => expect(page.getByRole("menuitem", { name: "Close 25 %" })).toHaveFocus());
  },
};

/** A close in flight: "Closing…" stays, a static ⟳ leads it, `aria-busy`; no lock, no reason (E29-D02:341). */
export const Busy: Story = {
  args: { busy: true, primary: { label: "Close", busyLabel: "Closing…", onClick: fn() } },
  render: (args) => (
    <SplitButton
      {...args}
      items={closeItems().map((item) =>
        ["sltp", "chart"].includes(item.id) ? item : { ...item, disabledReason: IN_FLIGHT },
      )}
    />
  ),
  play: async ({ canvasElement, args }) => {
    const busy = primaryOf(canvasElement, "Closing…");
    await expect(busy).toHaveAttribute("aria-busy", "true");
    await expect(busy).not.toHaveAttribute("aria-disabled");
    await expect(busy).not.toHaveAccessibleDescription(IN_FLIGHT);
    // The label stays visible: CMP-001's spinner overlay is not this look.
    await expect(busy.querySelector(".cv-button__label")).toBeVisible();
    await userEvent.click(busy);
    await expect(args.primary.onClick).not.toHaveBeenCalled();
  },
};

/** A Viewer: the primary is T2 (2b), its reason the description, echoed on focus; the ▾ repeats it per item. */
export const T2Reason: Story = {
  args: { allowed: false, reason: VIEWER },
  play: async ({ canvasElement, args }) => {
    const gated = primaryOf(canvasElement);
    await userEvent.tab();
    await expect(gated).toHaveFocus();
    await expect(gated).toHaveAttribute("aria-disabled", "true");
    await expect(gated).not.toBeDisabled();
    await expect(gated).toHaveAccessibleDescription(VIEWER);
    await userEvent.keyboard("{Enter} ");
    await expect(args.primary.onClick).not.toHaveBeenCalled();
  },
};

/** The ▾ menu of a gated split button: every item keeps its label, the reason as its second line. */
export const T2ReasonMenu: Story = {
  args: { allowed: false, reason: VIEWER },
  play: async ({ canvasElement }) => {
    await userEvent.click(toggleOf(canvasElement));
    const item = await within(document.body).findByRole("menuitem", { name: "Close 25 %" });
    await expect(item).toHaveAttribute("aria-disabled", "true");
    await expect(item).toHaveAccessibleDescription(VIEWER);
  },
};

/** CMP-079 RbacGate wraps it for the role legs, view-as first (E09-D09 §2.1). */
export const T2ViaRbacGate: Story = {
  render: (args) => (
    <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: "alex" }}>
      <SplitButton {...args} items={closeItems()} />
    </RbacGate>
  ),
  play: async ({ canvasElement }) => {
    await expect(primaryOf(canvasElement)).toHaveAccessibleDescription(
      "Read-only while viewing as alex.",
    );
  },
};

/** Working orders' row: "Cancel ▾" with the editor items (E29-D02:345). */
export const CancelOrder: Story = {
  args: {
    primary: { label: "Cancel", onClick: fn() },
    menuLabel: "More order actions, BTCUSDT Long on Main",
  },
  render: (args) => (
    <SplitButton
      {...args}
      items={[
        { id: "price", label: "Edit price", onSelect: fn() },
        { id: "trigger", label: "Edit trigger", onSelect: fn() },
        { id: "qty", label: "Edit qty", onSelect: fn() },
        { id: "chart", label: "Chart", onSelect: fn() },
      ]}
    />
  ),
};

/** The deck's longest words on the primary: it widens to fit, never truncating a verb (E29-D02 D-8). */
export const LongText: Story = {
  args: { primary: { label: "Close the full position", onClick: fn() } },
};

/** Default, busy and T2 under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => (
    <div style={{ display: "flex", gap: "var(--space-inset-md)", alignItems: "center" }}>
      <SplitButton
        primary={{ label: "Close", onClick: fn() }}
        menuLabel={MORE_CLOSE}
        items={closeItems()}
      />
      <SplitButton
        busy
        primary={{ label: "Close", busyLabel: "Closing…", onClick: fn() }}
        menuLabel="More close actions, ETHUSDT Short on Sub-1"
        items={closeItems()}
      />
      <SplitButton
        allowed={false}
        reason={VIEWER}
        primary={{ label: "Close", onClick: fn() }}
        menuLabel="More close actions, SOLUSDT Long on Sub-2"
        items={closeItems()}
      />
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
