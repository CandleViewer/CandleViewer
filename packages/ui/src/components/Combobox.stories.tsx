import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX, type ReactNode } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Icon } from "../icons/Icon.js";
import { Combobox, type ComboboxOption } from "./Combobox.js";
import { FormField } from "./FormField.js";
import { RbacGate } from "./RbacGate.js";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"].map((s) => ({ value: s, label: s }));
/** The host's sentences: SCR-102's no-results line (`14` SCR-102) and E08-D05's failed instrument list. */
const noMatch = (query: string): string => `No USDT perpetual matches '${query.trim()}'.`;
const FAILED = "Couldn't load the instrument list.";
const REASON = "Read-only while viewing as alex.";

type HostProps = {
  readonly search?: () => Promise<readonly ComboboxOption[]>;
  readonly prefix?: ReactNode;
  /** The text the host starts with ("BTC" for the default cell). */
  readonly initial?: string;
  /** Local options other than the four symbols (a gated option, a long label). */
  readonly options?: readonly ComboboxOption[];
};

/** A host that owns the text, as every consumer does: local symbols, or its own search. */
function Host({ search, prefix, initial = "", options = SYMBOLS }: HostProps): JSX.Element {
  const [value, setValue] = useState(initial);
  const source =
    search === undefined
      ? { options }
      : { asyncSearch: search, noResultsText: noMatch(value), searchFailedText: FAILED };
  return (
    <FormField label="Symbol">
      <Combobox
        {...source}
        value={value}
        onChange={setValue}
        placeholder="Search symbols"
        prefix={prefix}
      />
    </FormField>
  );
}

/** Theme and density come from the toolbars; the results portal under `body`, so plays query the page. */
const meta: Meta = {
  title: "Molecules/Combobox",
  component: Combobox,
  decorators: [
    (Story) => (
      <div style={{ width: "20rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj;

const page = within(document.body);
const input = (canvasElement: HTMLElement): HTMLElement =>
  within(canvasElement).getByRole("combobox", { name: "Symbol" });
const list = (): HTMLElement => page.getByRole("listbox", { name: "Symbol" });
const statusRow = (text: string): HTMLElement =>
  page.getByText(text, { selector: ".cv-combobox__status span" });

/** Default: "BTC" in the well, the list closed (E05-D02 CMP-048, the default cell). */
export const Default: Story = {
  render: () => <Host initial="BTC" />,
  play: async ({ canvasElement }) => {
    await expect(input(canvasElement)).toHaveValue("BTC");
    await expect(input(canvasElement)).toHaveAttribute("aria-expanded", "false");
  },
};

/** Hover: the well's hover look; nothing opens. */
export const Hover: Story = {
  render: () => <Host initial="BTC" />,
  play: async ({ canvasElement }) => {
    await userEvent.hover(input(canvasElement));
    await expect(input(canvasElement)).toHaveAttribute("aria-expanded", "false");
  },
};

/** FocusVisible: reached by Tab, the focus ring on the well; nothing opens. */
export const FocusVisible: Story = {
  render: () => <Host initial="BTC" />,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(input(canvasElement)).toHaveFocus();
    await expect(input(canvasElement)).toHaveAttribute("aria-expanded", "false");
  },
};

/** Sync: a `search` prefix; local options filter at the settle, the match in body-strong; ↓ leaves it open. */
export const Sync: Story = {
  render: () => <Host prefix={<Icon name="search" />} />,
  play: async ({ canvasElement }) => {
    await userEvent.type(input(canvasElement), "eth");
    await waitFor(() => expect(list()).toBeVisible(), { timeout: 3000 });
    await userEvent.keyboard("{ArrowDown}");
    const option = page.getByRole("option", { name: "ETHUSDT" });
    await expect(input(canvasElement)).toHaveAttribute("aria-activedescendant", option.id);
    await expect(input(canvasElement)).toHaveAttribute("aria-expanded", "true");
  },
};

/** AsyncLoading: once the query settles, the search is in flight: "Searching…", the listbox busy. */
export const AsyncLoading: Story = {
  render: () => <Host search={() => new Promise(() => undefined)} />,
  play: async ({ canvasElement }) => {
    await userEvent.type(input(canvasElement), "BTC");
    await waitFor(() => expect(statusRow("Searching…")).toBeVisible(), { timeout: 3000 });
    await expect(list()).toHaveAttribute("aria-busy", "true");
  },
};

/** NoResults: once the query settles, the host's sentence in a status row; it is not an option. */
export const NoResults: Story = {
  render: () => <Host search={async () => []} />,
  play: async ({ canvasElement }) => {
    await userEvent.type(input(canvasElement), "xyz");
    await waitFor(() => expect(statusRow(noMatch("xyz"))).toBeVisible(), { timeout: 3000 });
    await expect(page.queryAllByRole("option")).toHaveLength(0);
  },
};

/** SearchFailed: the `danger` glyph and the host's sentence; the query is kept. */
export const SearchFailed: Story = {
  render: () => <Host search={() => Promise.reject(new Error("offline"))} />,
  play: async ({ canvasElement }) => {
    await userEvent.type(input(canvasElement), "BTC");
    await waitFor(() => expect(statusRow(FAILED)).toBeVisible(), { timeout: 3000 });
    await expect(input(canvasElement)).toHaveValue("BTC");
  },
};

/** Invalid: free text that names no listed symbol; the 2 px boundary, and CMP-040's line says why. */
export const Invalid: Story = {
  render: () => (
    <FormField label="Symbol" error="Choose a listed symbol.">
      <Combobox options={SYMBOLS} value="BTC" onChange={() => undefined} />
    </FormField>
  ),
  play: async ({ canvasElement }) => {
    await expect(input(canvasElement)).toHaveAttribute("aria-invalid", "true");
    await expect(input(canvasElement)).toHaveAccessibleDescription("Choose a listed symbol.");
  },
};

/** Disabled (plain): Tab skips the well, and nothing opens. */
export const Disabled: Story = {
  render: () => (
    <FormField label="Symbol">
      <Combobox options={SYMBOLS} value="BTC" onChange={() => undefined} disabled />
    </FormField>
  ),
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(input(canvasElement)).not.toHaveFocus();
    await expect(input(canvasElement)).toBeDisabled();
  },
};

/** DisabledWithReason: T2 through CMP-079 and CMP-040; the lock leads the value, keys change nothing. */
export const DisabledWithReason: Story = {
  render: () => (
    <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: "alex" }}>
      <FormField label="Symbol">
        <Combobox options={SYMBOLS} value="BTC" onChange={() => undefined} />
      </FormField>
    </RbacGate>
  ),
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(input(canvasElement)).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}x");
    await expect(input(canvasElement)).toHaveAttribute("aria-expanded", "false");
    await expect(input(canvasElement)).toHaveAccessibleDescription(REASON);
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent(REASON);
  },
};

/** A gated option (T2): the lock, the label in the tertiary colour and its reason; reached, never chosen. */
export const GatedOption: Story = {
  render: () => (
    <Host
      options={[
        { value: "ETHUSDT", label: "ETHUSDT" },
        { value: "ETHPERP", label: "ETHPERP", disabledReason: "Not traded on this account." },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await userEvent.type(input(canvasElement), "eth");
    await waitFor(() => expect(list()).toBeVisible(), { timeout: 3000 });
    await expect(page.getByRole("option", { name: "ETHPERP" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  },
};

/** A long label wraps onto a second line, then truncates. */
export const LongLabel: Story = {
  render: () => (
    <Host
      options={[
        {
          value: "LONG",
          label: "A long option label that wraps onto a second line and then truncates at the edge",
        },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await userEvent.type(input(canvasElement), "long");
    await waitFor(() => expect(list()).toBeVisible(), { timeout: 3000 });
  },
};
