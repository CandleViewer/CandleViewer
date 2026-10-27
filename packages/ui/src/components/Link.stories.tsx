import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Link, type LinkSlotProps } from "./Link.js";

const DOCS = "https://example.com/api-docs";
const onNavigate = fn();

/** A stand-in for the app's router link: it renders the `<a>` and navigates in-app (here: records it). */
function RouterLink({ to, onClick, children, ...rest }: LinkSlotProps): JSX.Element {
  return (
    <a
      {...rest}
      href={to}
      onClick={(event) => {
        onClick?.(event);
        event.preventDefault();
        onNavigate(to);
      }}
    >
      {children}
    </a>
  );
}

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Link> = {
  title: "Atoms/Link",
  component: Link,
};
export default meta;
type Story = StoryObj<typeof Link>;

const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;
const link = (canvas: HTMLElement, name: string | RegExp): HTMLElement =>
  within(canvas).getByRole("link", { name });

export const Default: Story = {
  render: () => <Link href="#settings">Shortcut settings</Link>,
};

/** An in-app route through the router slot: the app passes its router link as `as`. */
export const Internal: Story = {
  render: () => (
    <Link to="/settings/shortcuts" as={RouterLink}>
      Shortcut settings
    </Link>
  ),
  play: async ({ canvasElement }) => {
    onNavigate.mockClear();
    await userEvent.tab();
    const el = link(canvasElement, "Shortcut settings");
    await expect(el).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(onNavigate).toHaveBeenCalledWith("/settings/shortcuts");
  },
};

/** External: the glyph, the hidden suffix in the name and `rel="noopener noreferrer"` (E25). */
export const External: Story = {
  render: () => (
    <Link href={DOCS} external>
      Bybit API documentation
    </Link>
  ),
  play: async ({ canvasElement }) => {
    const el = link(canvasElement, "Bybit API documentation (opens externally)");
    await expect(el).toHaveAttribute("rel", "noopener noreferrer");
    await expect(el).toHaveAttribute("target", "_blank");
  },
};

export const Hover: Story = {
  ...Default,
  play: async ({ canvasElement }) => userEvent.hover(link(canvasElement, "Shortcut settings")),
};

/** The CMP-039 ring at the link's own square corners (E8). */
export const FocusVisible: Story = {
  ...Default,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    const el = link(canvasElement, "Shortcut settings");
    await expect(el).toHaveFocus();
    await expect(parseFloat(getComputedStyle(el).borderRadius)).toBe(0);
  },
};

export const ExternalFocusVisible: Story = {
  ...External,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(link(canvasElement, /opens externally/)).toHaveFocus();
  },
};

/** Plain disabled: `role="link"`, `aria-disabled`, no href, skipped by Tab. Gated links are held (E27). */
export const Disabled: Story = {
  render: () => (
    <div style={col}>
      <Link href="#settings" disabled>
        Shortcut settings
      </Link>
      <Link href={DOCS} external disabled>
        Bybit API documentation
      </Link>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const el = link(canvasElement, "Shortcut settings");
    await expect(el).toHaveAttribute("aria-disabled", "true");
    await expect(el).not.toHaveAttribute("href");
    await userEvent.tab();
    await expect(document.body).toHaveFocus();
  },
};

/** Inline in a sentence: the link wraps with it, the underline follows each line, the glyph stays on the last word. */
export const LongText: Story = {
  render: () => (
    <p style={{ width: "16rem", margin: 0 }}>
      Read the{" "}
      <Link href={DOCS} external>
        Bybit v5 API documentation on rate limits per UID and endpoint class
      </Link>{" "}
      before you raise a budget, or open{" "}
      <Link to="/settings/shortcuts" as={RouterLink}>
        Shortcut settings
      </Link>
      .
    </p>
  ),
};

/** Every state under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => (
    <div style={col}>
      <Link href="#settings">Shortcut settings</Link>
      <Link href={DOCS} external>
        Bybit API documentation
      </Link>
      <Link href="#settings" disabled>
        Shortcut settings
      </Link>
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
