import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, userEvent, within } from "storybook/test";
import { StaleDataShade, staleAsOf, staleDataRowClassName } from "./StaleDataShade.js";

/** The design-system face on the stories' wrapper, so a host's own text never falls back to the browser's serif. */
const FONT = "var(--font-family-ui), system-ui, sans-serif";
/** 2026-11-03 14:02:11 UTC: the deck's sample time. */
const AT = Date.UTC(2026, 10, 3, 14, 2, 11);

/**
 * A stand-in panel: a region named by its header, described by the shade's words, with one focusable control. It has
 * no exit control (no Close, Cancel or stop): the `disconnected` scrim takes the pointer and must never sit over one
 * (C-2.6, E17-D01 A1).
 */
function Panel({ described }: { readonly described: string }): JSX.Element {
  return (
    <section aria-label="Positions" aria-describedby={described} style={{ padding: "0.5rem" }}>
      <table>
        <caption>Positions</caption>
        <tbody>
          <tr>
            <th scope="row">BTCUSDT</th>
            <td>0.250</td>
            <td>
              <button type="button">Details</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}

/**
 * CMP-078 StaleDataShade (E17-D02 §7; E29-D03 §4.4's account scope): the panel's last values stay under a dim or a
 * scrim, the words above it. Every state is a story (`15` CMP-078 Storybook: Fresh, Stale, Escalated, StaleServer,
 * Disconnected, ReducedMotion), plus the account scope, the grid row, long text, hover and keyboard focus.
 */
const meta: Meta<typeof StaleDataShade> = {
  title: "Molecules/StaleDataShade",
  component: StaleDataShade,
  args: { id: "shade-words", state: "stale", ageMs: 7000 },
  render: (args) => (
    <StaleDataShade {...args}>
      <Panel described={args.id} />
    </StaleDataShade>
  ),
  decorators: [
    (Story) => (
      <div style={{ fontFamily: FONT, width: "28rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof StaleDataShade>;

const words = (canvasElement: HTMLElement): HTMLElement | null =>
  canvasElement.querySelector<HTMLElement>("#shade-words");

/** Fresh: nothing is drawn, no dim and no words; the panel is the same node (never remounted). */
export const Fresh: Story = {
  args: { state: "fresh" },
  play: async ({ canvasElement }) => {
    await expect(words(canvasElement)).toBeNull();
    await expect(canvasElement.querySelector(".cv-stale-shade__dim")).toBeNull();
  },
};

/** Stale (T1): the 15 % dim, the chip "Stale 7s" and "Last update 7 s ago". */
export const Stale: Story = {
  play: async ({ canvasElement }) => {
    await expect(words(canvasElement)).toHaveTextContent("Last update 7 s ago");
    await expect(within(canvasElement).getByText("Stale, 7 seconds")).toBeInTheDocument();
  },
};

/** Escalated (T2): the header strip with the host's sentence, the strong chip. */
export const Escalated: Story = {
  args: { state: "escalated", ageMs: 15_000, strip: "Stale 15 s — new orders blocked on BTCUSDT" },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText("Stale 15 s — new orders blocked on BTCUSDT"),
    ).toBeInTheDocument();
  },
};

/** Stale (server): the snapshot's own flag, "since" its time; no cause is shown. */
export const StaleServer: Story = {
  args: { state: "stale-server", sinceTs: AT },
  play: async ({ canvasElement }) => {
    await expect(words(canvasElement)).toHaveTextContent("Stale (server) — since 14:02:11");
  },
};

/** Disconnected: the held last frame under the scrim, "Disconnected — last data 00:12". */
export const Disconnected: Story = {
  args: { state: "disconnected", ageMs: 12_000 },
  play: async ({ canvasElement }) => {
    await expect(words(canvasElement)).toHaveTextContent("Disconnected — last data 00:12");
  },
};

/** The stale lock at account scope (E29-D03 §4.4, D04 `CMP-114/row-stale`): "Not up to date · as of …". */
export const AccountScope: Story = {
  args: { state: "stale", lastGoodTs: AT },
  // no `ageMs`: the account scope has none to give, so none is drawn (the meta's 7 s is not inherited)
  render: (args) => (
    <StaleDataShade id={args.id} state="stale" lastGoodTs={AT}>
      <Panel described={args.id} />
    </StaleDataShade>
  ),
  play: async ({ canvasElement }) => {
    await expect(words(canvasElement)).toHaveTextContent("Not up to date · as of 14:02:11 UTC");
    // No age was given, so none is drawn: no chip and no "Stale 0s" (C-2.12).
    await expect(canvasElement.querySelector(".cv-freshness-chip")).toBeNull();
  },
};

/** Reduced motion: the shade is a flip in every mode, so this story equals Stale with motion reduced. */
export const ReducedMotion: Story = {
  globals: { motion: "reduce" },
  play: async ({ canvasElement }) => {
    await expect(words(canvasElement)).toHaveTextContent("Last update 7 s ago");
    const running = canvasElement.getAnimations?.({ subtree: true }) ?? [];
    await expect(running).toHaveLength(0);
  },
};

/** A long host label wraps; nothing is cut or ellipsised. */
export const LongText: Story = {
  args: {
    label:
      "Sub-2 · LIVE — not up to date · as of 14:02:11 UTC · the rows show the last values Bybit confirmed",
  },
};

/** Hover: the dim takes no pointer, so the row underneath keeps its hover and its button. */
export const Hover: Story = {
  play: async ({ canvasElement }) => {
    const close = within(canvasElement).getByRole("button", { name: "Details" });
    await userEvent.hover(close);
    await expect(close).toBeVisible();
  },
};

/** Keyboard focus: the panel's control stays in the Tab order under the shade (never `inert`). */
export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("button", { name: "Details" })).toHaveFocus();
  },
};

/** The grid-row variant: a class swap on the row, its description ending "as of … UTC". */
export const GridRow: Story = {
  render: () => (
    <table>
      <caption>Orders</caption>
      <tbody>
        <tr className={staleDataRowClassName("stale")} aria-describedby="row-as-of">
          <th scope="row">ETHUSDT</th>
          <td>2,500.00</td>
          <td id="row-as-of">{staleAsOf(AT)}</td>
        </tr>
      </tbody>
    </table>
  ),
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("tr")).toHaveClass("cv-stale-row--stale");
    await expect(within(canvasElement).getByText("as of 14:02:11 UTC")).toBeInTheDocument();
  },
};
