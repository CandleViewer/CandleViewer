import type { Meta, StoryObj } from "@storybook/react-vite";
import { NotFoundState } from "./NotFoundState.js";

/** CMP-090 (SCR-155). Theme and density come from the toolbars. */
const meta: Meta<typeof NotFoundState> = {
  title: "Organisms/NotFoundState",
  component: NotFoundState,
  args: {
    path: "/nowhere",
    tryRoutes: [
      { label: "Terminal", href: "/terminal" },
      { label: "Journal", href: "/journal" },
      { label: "Settings", href: "/settings" },
    ],
  },
};
export default meta;
type Story = StoryObj<typeof NotFoundState>;

/** An unknown route. */
export const Default: Story = {};

/**
 * `/admin/users` for a session without `admin:read`: identical to Default (same copy, title and
 * analytics; D09 §6), only the echoed route differs.
 */
export const Admin: Story = { args: { path: "/admin/users" } };

/** A deleted object (`14` SCR-155): its own sentence instead of the route echo. */
export const Deleted: Story = { args: { variant: "deleted", path: "/terminal/ws_42" } };
