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

/** The CMP-039 ring at the link's own square corners (E8): the ring class, drawn as the token outline. */
export const FocusVisible: Story = {
  ...Default,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    const el = link(canvasElement, "Shortcut settings");
    await expect(el).toHaveFocus();
    await expect(el).toHaveClass("cv-focus-ring");
    await expect(el.matches(":focus-visible")).toBe(true);
    const style = getComputedStyle(el);
    await expect(style.outlineStyle).toBe("solid");
    await expect(parseFloat(style.outlineWidth)).toBeGreaterThan(0);
    // The outline colour is the color.focus.ring token, resolved on the root.
    const probe = document.createElement("span");
    probe.style.color = "var(--color-focus-ring)";
    document.body.append(probe);
    const ring = getComputedStyle(probe).color;
    probe.remove();
    await expect(style.outlineColor).toBe(ring);
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

const WRAP_TEXT = "Bybit API documentation for rate limits";

/**
 * The glyph never wraps alone: across every container width from 6rem to 20rem (1px steps), the glyph's
 * line is the line of the link's last word, so each width that breaks before the glyph breaks a word earlier.
 */
export const ExternalNarrowWrap: Story = {
  render: () => (
    <p data-testid="wrap-host" style={{ width: "6rem", margin: 0 }}>
      <Link href={DOCS} external>
        {WRAP_TEXT}
      </Link>
    </p>
  ),
  play: async ({ canvasElement }) => {
    const host = within(canvasElement).getByTestId("wrap-host");
    const anchor = link(canvasElement, /opens externally/);
    const glyph = anchor.querySelector(".cv-link__glyph");
    const text = anchor.firstChild;
    if (glyph === null || text === null) throw new Error("no glyph or text");
    const range = document.createRange();
    range.selectNodeContents(text);
    let wrapped = 0;
    for (let px = 96; px <= 320; px += 1) {
      host.style.width = `${px}px`;
      const lines = Array.from(range.getClientRects());
      const last = lines[lines.length - 1];
      if (last === undefined) throw new Error("no text line");
      if (lines.length > 1) wrapped += 1;
      const box = glyph.getBoundingClientRect();
      const middle = box.top + box.height / 2;
      // The glyph's middle sits within the last text line's box: same line, never alone below it.
      await expect(middle).toBeGreaterThanOrEqual(last.top);
      await expect(middle).toBeLessThanOrEqual(last.bottom);
    }
    // The sweep is only meaningful if the text really wrapped at the narrow widths.
    await expect(wrapped).toBeGreaterThan(0);
  },
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
