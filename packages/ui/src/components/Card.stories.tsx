import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { Button } from "./Button.js";
import { Card } from "./Card.js";
import { IconButton } from "./IconButton.js";
import { KeyValueRow } from "./KeyValueRow.js";
import { Link } from "./Link.js";

const body = <p style={{ margin: 0 }}>Three accounts are connected; one key expires in 12 days.</p>;

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Card> = {
  title: "Molecules/Card",
  component: Card,
  args: { title: "Accounts", children: body },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: "24rem", padding: "var(--space-inset-lg)" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof Card>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { level: 3, name: "Accounts" })).toBeVisible();
    await expect(canvas.queryByRole("region")).toBeNull();
  },
};

export const Flat: Story = { args: { surface: "flat" } };

export const NoHeader: Story = { args: { title: undefined } };

export const WithActions: Story = {
  args: {
    actions: (
      <>
        <IconButton icon="more-horizontal" label="More actions for Accounts" variant="ghost" />
        <Button size="sm">Manage</Button>
      </>
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const [heading, more, manage] = [
      canvas.getByRole("heading", { name: "Accounts" }),
      canvas.getByRole("button", { name: "More actions for Accounts" }),
      canvas.getByRole("button", { name: "Manage" }),
    ];
    // DOM order: header (title, then actions), then body.
    await expect(heading.compareDocumentPosition(more) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    await expect(more.compareDocumentPosition(manage) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  },
};

/** Padding=none: the child runs edge to edge (a CMP-049 table in its final form). */
export const NoPadding: Story = {
  args: {
    title: "Recent fills",
    padding: "none",
    children: (
      <dl style={{ display: "grid", margin: 0 }}>
        <KeyValueRow label="BTCUSDT" value="0.250 BTC" />
        <KeyValueRow label="ETHUSDT" value="4.000 ETH" />
      </dl>
    ),
  },
};

/** An admin home tile (E42-D03): a region landmark named by its heading, which is a link. */
export const RegionTile: Story = {
  args: {
    region: true,
    headingLevel: 2,
    title: <Link href="#audit">Audit log</Link>,
    children: body,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("region", { name: "Audit log" })).toBeVisible();
    await expect(canvas.getByRole("heading", { level: 2, name: "Audit log" })).toBeVisible();
  },
};

/** headingLevel 0: inside a listbox option (E15-D05 A-4) the title is plain text, never a heading. */
export const InOption: Story = {
  args: { headingLevel: 0, title: "Scalping layout", surface: "flat" },
  render: (args) => (
    <div role="listbox" aria-label="Layouts">
      <div role="option" aria-selected="false">
        <Card {...args} />
      </div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("heading")).toBeNull();
    await expect(canvas.getByRole("option")).toHaveTextContent("Scalping layout");
  },
};

/** Conventions 49: a long title wraps before the actions move under it. */
export const LongTitle: Story = {
  args: {
    title: "Per-account risk profile and notional caps for the managed sub-accounts",
    actions: <IconButton icon="more-horizontal" label="More actions" variant="ghost" />,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const heading = canvas.getByRole("heading").getBoundingClientRect();
    const action = canvas.getByRole("button").getBoundingClientRect();
    await expect(action.left).toBeGreaterThanOrEqual(heading.right - 1);
  },
};

/** Every cell side by side (spec matrix): elevated, flat, actions, no padding, region tile. */
export const AllStates: Story = {
  render: () => (
    <div style={{ display: "grid", gap: "var(--space-inset-lg)" }}>
      <Card title="Elevated">{body}</Card>
      <Card title="Flat" surface="flat">
        {body}
      </Card>
      <Card
        title="With actions"
        actions={<IconButton icon="more-horizontal" label="More actions for With actions" />}
      >
        {body}
      </Card>
      <Card title="No padding" padding="none">
        {body}
      </Card>
      <Card region title={<Link href="#tile">Region tile</Link>} headingLevel={2}>
        {body}
      </Card>
    </div>
  ),
};
