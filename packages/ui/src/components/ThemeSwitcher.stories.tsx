import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { ThemeProvider, createThemeStore, type ThemeName } from "../theme/index.js";
import { ThemeSwitcher, ThemeSwitcherConnected, type ThemeSwitcherProps } from "./ThemeSwitcher.js";

/**
 * Theme, density and motion come from the toolbars, so every story renders at each of the 3 x 2
 * combinations and under reduced motion. The props-only stories never re-theme the page (the toolbar
 * owns it); `Connected` binds a private store whose root is detached, so the preview stays put.
 */
const meta: Meta<typeof ThemeSwitcher> = {
  title: "Molecules/ThemeSwitcher",
  parameters: {
    docs: {
      description: {
        component:
          "No disabled-with-reason form: J15 (a) is built (every role changes the appearance on this device, no T2); (b), T2 through CMP-079, is the gated alternative pending the owner on #2701.",
      },
    },
  },
  component: ThemeSwitcher,
  args: { value: "dark", onChange: fn(), onMatchSystemChange: fn() },
};
export default meta;
type Story = StoryObj<typeof ThemeSwitcher>;

/** A host that applies the change as the store would (a segment turns match system off; on resolves to light). */
function Controlled(props: ThemeSwitcherProps): JSX.Element {
  const [value, setValue] = useState<ThemeName>(props.value);
  const [matchSystem, setMatchSystem] = useState(props.matchSystem ?? false);
  return (
    <ThemeSwitcher
      {...props}
      value={value}
      matchSystem={matchSystem}
      onChange={(next) => {
        setValue(next);
        setMatchSystem(false);
        props.onChange?.(next);
      }}
      onMatchSystemChange={(on) => {
        setMatchSystem(on);
        if (on) setValue("light");
        props.onMatchSystemChange?.(on);
      }}
    />
  );
}
const controlled: Story["render"] = (args) => <Controlled {...args} />;
const radio = (canvas: HTMLElement, name: string): HTMLElement =>
  within(canvas).getByRole("radio", { name });

/** J13 dark cell: dark is the default. */
export const Default: Story = { render: controlled };

export const Light: Story = { args: { value: "light" }, render: controlled };

export const HighContrast: Story = { args: { value: "high-contrast" }, render: controlled };

/** J13 match-system cell: the switch on, the segment the system resolves to checked; no interaction. */
export const MatchSystem: Story = {
  args: { value: "light", matchSystem: true },
  render: controlled,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("switch")).toBeChecked();
    await expect(radio(canvasElement, "Light")).toBeChecked();
  },
};

/** With match system on, picking a segment commits it and turns the switch off. */
export const MatchSystemThenPick: Story = {
  args: { value: "light", matchSystem: true },
  render: controlled,
  play: async ({ canvasElement, args }) => {
    await expect(within(canvasElement).getByRole("switch")).toBeChecked();
    await userEvent.click(radio(canvasElement, "Dark"));
    await expect(args.onChange).toHaveBeenCalledWith("dark");
    await expect(within(canvasElement).getByRole("switch")).not.toBeChecked();
  },
};

/** The CMP-039 ring on the checked segment. */
export const FocusVisible: Story = {
  render: controlled,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(radio(canvasElement, "Dark")).toHaveFocus();
  },
};

export const Hover: Story = {
  render: controlled,
  play: async ({ canvasElement }) => userEvent.hover(radio(canvasElement, "Light")),
};

/** J16: each arrow is a committed change; the region's text is replaced, so it speaks the last value. */
export const KeyboardAnnounce: Story = {
  render: controlled,
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    await expect(args.onChange).toHaveBeenCalledTimes(2);
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent(
      "Theme changed to High Contrast",
    );
  },
};

export const Disabled: Story = { args: { disabled: true } };

/** Longer copy (a translation): the switch wraps under the segments instead of overflowing. */
export const LongText: Story = {
  args: {
    copy: {
      label: "Application colour theme",
      dark: "Dark (default)",
      light: "Light for bright rooms",
      highContrast: "High contrast for low vision",
      matchSystem: "Match the operating system's appearance setting",
    },
  },
  render: controlled,
  decorators: [
    (Story) => (
      <div style={{ maxWidth: "28rem" }}>
        <Story />
      </div>
    ),
  ],
};

export const Comfortable: Story = { args: { density: "comfortable" }, render: controlled };

/** Store-bound: writes through a private store, which persists and emits the analytics (J16). */
function ConnectedHost(): JSX.Element {
  const [store] = useState(() =>
    createThemeStore({
      root: document.createElement("div"),
      storage: { getItem: () => null, setItem: () => undefined },
    }),
  );
  return (
    <ThemeProvider store={store}>
      <ThemeSwitcherConnected />
    </ThemeProvider>
  );
}

export const Connected: Story = {
  render: () => <ConnectedHost />,
  play: async ({ canvasElement }) => {
    await userEvent.click(radio(canvasElement, "High contrast"));
    await expect(radio(canvasElement, "High contrast")).toBeChecked();
  },
};
