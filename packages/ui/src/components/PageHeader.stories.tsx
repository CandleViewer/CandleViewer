import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, userEvent, within } from "storybook/test";
import { Button } from "./Button.js";
import { Link } from "./Link.js";
import { PageHeader } from "./PageHeader.js";

/** The admin content column at 1280 (E42-D03 D1, 944 px), in the system's body type and text colour. */
const frame = {
  maxWidth: "59rem",
  color: "var(--color-text-primary)",
  font: "var(--type-ui-body-font-weight) var(--type-ui-body-font-size) / var(--type-ui-body-line-height) var(--type-ui-body-font-family)",
} as const;

/**
 * A stand-in for the host's CMP-052 Breadcrumb, which is not built yet: `nav` "Breadcrumb", an ordered
 * list, the current page last with `aria-current="page"` (`15` CMP-052 A11y).
 */
function StandInBreadcrumb(): JSX.Element {
  return (
    <nav aria-label="Breadcrumb">
      <ol
        style={{
          display: "flex",
          gap: "var(--space-inset-xs)",
          margin: 0,
          padding: 0,
          listStyle: "none",
          color: "var(--color-text-secondary)",
        }}
      >
        <li>
          <Link href="#settings">Settings</Link>
        </li>
        <li>
          <span aria-hidden="true">/ </span>
          <span aria-current="page">Hotkeys</span>
        </li>
      </ol>
    </nav>
  );
}

const inviteUser = (
  <Button variant="primary" iconLeft="plus">
    Invite user
  </Button>
);

/** SCR-121's header with its UTC "as of" line: the args AdminWithMeta, Hover and FocusVisible share. */
const adminWithMeta = {
  title: "Users",
  actions: inviteUser,
  meta: "All times UTC · as of 14:02:11",
};

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof PageHeader> = {
  title: "Molecules/PageHeader",
  component: PageHeader,
  args: { title: "Settings" },
  decorators: [
    (Story) => (
      <div style={frame}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof PageHeader>;

const heading = (canvas: HTMLElement): HTMLElement =>
  within(canvas).getByRole("heading", { level: 1 });

/** The page's name alone: one `h1`, nothing else. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getAllByRole("heading", { level: 1 })).toHaveLength(1);
    await expect(heading(canvasElement)).toHaveTextContent("Settings");
    await expect(within(canvasElement).queryByRole("navigation")).toBeNull();
  },
};

/** Outside the admin area: the host's breadcrumb above the title (SCR-110's Settings sections). */
export const WithBreadcrumb: Story = {
  args: { title: "Hotkeys", breadcrumb: <StandInBreadcrumb /> },
  play: async ({ canvasElement }) => {
    const nav = within(canvasElement).getByRole("navigation", { name: "Breadcrumb" });
    await expect(
      nav.compareDocumentPosition(heading(canvasElement)) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  },
};

/** An admin sub-page (SCR-121): no breadcrumb, the band carries the route; the primary action after the `h1`. */
export const Admin: Story = {
  args: { title: "Users", actions: inviteUser },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("navigation")).toBeNull();
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("button", { name: "Invite user" })).toHaveFocus();
  },
};

/** The UTC "as of" line under the title (`meta.asof`), plain text and never live. */
export const AdminWithMeta: Story = {
  args: adminWithMeta,
  play: async ({ canvasElement }) => {
    const line = within(canvasElement).getByText("All times UTC · as of 14:02:11");
    await expect(line.closest("[aria-live], [role='status'], [role='alert']")).toBeNull();
  },
};

/** An audited read (SCR-135): the meta, then the marker line (E42-D04 `audit.marker`), never a toast. */
export const AdminAuditedRead: Story = {
  args: {
    title: "Audit log",
    meta: "All times UTC · as of 14:02:11",
    marker: "Viewing this log is recorded — Audit log viewed (admin.audit_read)",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const meta = canvas.getByText("All times UTC · as of 14:02:11");
    const marker = canvas.getByText(
      "Viewing this log is recorded — Audit log viewed (admin.audit_read)",
    );
    await expect(meta.compareDocumentPosition(marker) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    await expect(marker.closest("[aria-live], [role='status'], [role='alert']")).toBeNull();
  },
};

/** The pointer on the primary action: the header has no hover of its own, the button shows its own. */
export const Hover: Story = {
  args: adminWithMeta,
  play: async ({ canvasElement }) =>
    userEvent.hover(within(canvasElement).getByRole("button", { name: "Invite user" })),
};

/** Tab from the page start: the primary action is the first stop, with CMP-039's ring. */
export const FocusVisible: Story = {
  args: adminWithMeta,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    const action = within(canvasElement).getByRole("button", { name: "Invite user" });
    await expect(action).toHaveFocus();
    await expect(action.matches(":focus-visible")).toBe(true);
  },
};

/** At a narrow width the title and the meta wrap; the action keeps the title row's end, never truncating. */
export const LongText: Story = {
  args: {
    title: "Per-account risk profiles and notional caps for the managed sub-accounts",
    actions: inviteUser,
    meta: "All times UTC · as of 14:02:11 · the caps the server resolves for each sub-account",
  },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: "22rem" }}>
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const title = heading(canvasElement).getBoundingClientRect();
    const action = within(canvasElement).getByRole("button").getBoundingClientRect();
    await expect(action.left).toBeGreaterThanOrEqual(title.right - 1);
    // The title wrapped: taller than one line of its own type.
    await expect(title.height).toBeGreaterThan(action.height);
  },
};
