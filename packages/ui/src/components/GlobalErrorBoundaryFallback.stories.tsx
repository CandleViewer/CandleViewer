import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import {
  GLOBAL_ERROR_FALLBACK_COPY as C,
  GlobalErrorBoundaryFallback,
} from "./GlobalErrorBoundaryFallback.js";

const ID = "7f3a2c10-0000-4000-8000-000000000001";
const DETAILS = `2026-10-27T14:02:05.000Z crash panel ${ID} TypeError: Cannot read properties of undefined (reading 'bids')`;

/** CMP-091's five cells (E05-D02 §7): scope × details × repeated. Theme and density come from the toolbars. */
const meta: Meta<typeof GlobalErrorBoundaryFallback> = {
  title: "Organisms/GlobalErrorBoundaryFallback",
  component: GlobalErrorBoundaryFallback,
  args: {
    scope: "panel",
    correlationId: ID,
    onReload: fn(),
    onReloadApp: fn(),
    onRemovePanel: fn(),
    onSafeMode: fn(),
    onCopyDiagnostics: fn(async () => undefined),
  },
};
export default meta;
type Story = StoryObj<typeof GlobalErrorBoundaryFallback>;

export const PanelLevel: Story = {};

export const RouteLevel: Story = { args: { scope: "route" } };

export const AppLevel: Story = { args: { scope: "app" } };

export const RepeatedCrash: Story = {
  args: { repeated: true },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByRole("heading", { name: C.panel.repeatedHeading })).toBeVisible();
    await expect(c.queryByRole("button", { name: C.panel.reload })).toBeNull();
    await expect(c.getByRole("button", { name: C.reloadApp })).toBeVisible();
  },
};

export const WithDetails: Story = { args: { details: DETAILS } };

/** Details=open: the host-redacted string behind "Technical detail". */
export const Details: Story = {
  args: { details: DETAILS },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    const toggle = c.getByRole("button", { name: C.technicalDetail });
    await userEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "true"));
    await expect(c.getByText(DETAILS)).toBeVisible();
  },
};

/** Long text: the details scroll inside their box and the sentences wrap. */
export const LongDetails: Story = {
  args: {
    details: Array.from({ length: 40 }, (_, i) => `${DETAILS} #${i}`).join("\n"),
    protectionNote: "Positions are unaffected and protected by native stops.",
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: C.technicalDetail }));
  },
};
