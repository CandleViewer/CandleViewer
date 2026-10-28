import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Callout, type CalloutTone } from "./Callout.js";

/** The specimen board's sentences (E05-D02 §CMP-028 cells), one per tone. */
const TONES: readonly { tone: CalloutTone; title: string; body: string }[] = [
  {
    tone: "info",
    title: "Reconnected — backfilling history",
    body: "Recorded coverage catching up: 00:41 remaining.",
  },
  {
    tone: "warning",
    title: "Degraded — some data feeds are stale",
    body: "Book and tape are live; 1 of 4 topics stale 6s. Recent trades may lag.",
  },
  {
    tone: "danger",
    title: "Trading locked: daily loss limit −2 % reached at 13:41 UTC.",
    body: "New orders are blocked until the next session.",
  },
  {
    tone: "success",
    title: "Accepted — stop 63,900.0 held by the exchange",
    body: "Exchange id ends …5f60.",
  },
  {
    tone: "connection-reconnecting",
    title: "Connection unstable — last data 4s ago",
    body: "Trying to reconnect.",
  },
  {
    tone: "connection-disconnected",
    title: "Disconnected — reconnecting (attempt 3, next in 4 s)",
    body: "Last data 00:12 ago. Trading is disabled while offline.",
  },
];

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Callout> = {
  title: "Atoms/Callout",
  component: Callout,
  args: { tone: "info", title: TONES[0]?.title ?? "", children: TONES[0]?.body },
};
export default meta;
type Story = StoryObj<typeof Callout>;

const col = { display: "grid", gap: "var(--space-inset-sm)", maxWidth: "36rem" } as const;

export const Default: Story = {};

/** The six tones: each with its registry glyph and its words, never colour alone. */
export const AllTones: Story = {
  render: () => (
    <div style={col}>
      {TONES.map((t) => (
        <Callout key={t.tone} tone={t.tone} title={t.title} live="off">
          {t.body}
        </Callout>
      ))}
    </div>
  ),
};

/** Polite by default: a `status` region whose words land after mount, announced once. */
export const ConnectionReconnecting: Story = {
  args: { tone: "connection-reconnecting", title: TONES[4]?.title ?? "", children: TONES[4]?.body },
  play: async ({ canvasElement }) => {
    const region = await within(canvasElement).findByRole("status");
    await expect(region).toHaveTextContent("Connection unstable");
  },
};

/** Assertive by default, with "Retry now" and "Details" outside the alert so their names are not read with it. */
export const ConnectionDisconnected: Story = {
  args: {
    tone: "connection-disconnected",
    title: TONES[5]?.title ?? "",
    children: TONES[5]?.body,
    details: "Your exchange-side stop-losses are unaffected.",
    retry: { label: "Retry now", onClick: fn() },
    actions: [{ label: "Details", onClick: fn() }],
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const alert = await canvas.findByRole("alert");
    await expect(alert).toHaveTextContent("stop-losses are unaffected");
    await expect(alert).not.toHaveTextContent("Retry now");
    await userEvent.tab();
    await expect(canvas.getByRole("button", { name: "Retry now" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(args.retry?.onClick).toHaveBeenCalledTimes(1);
  },
};

/** A warning about the user's own choice or the form in view is read in context: the host passes `polite`. */
export const LivePolite: Story = {
  args: { tone: "warning", title: TONES[1]?.title ?? "", children: TONES[1]?.body, live: "polite" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("status")).toHaveTextContent("Degraded");
    await expect(canvas.queryByRole("alert")).toBeNull();
  },
};

/** The band: full width and square, `live="off"` (another region announced it), dismissible once read. */
export const Band: Story = {
  args: {
    placement: "band",
    title: "Your access changed just now.",
    children: undefined,
    live: "off",
    dismissible: true,
    onDismiss: fn(),
  },
};

/** The host removes the callout and moves focus to its own next stop; the callout never moves focus. */
function DismissHost(): JSX.Element {
  const [open, setOpen] = useState(true);
  const panel = useRef<HTMLElement>(null);
  return (
    <section ref={panel} tabIndex={-1} aria-label="Orders panel" style={col}>
      {open ? (
        <Callout
          title="Reconnected"
          dismissible
          onDismiss={() => {
            setOpen(false);
            requestAnimationFrame(() => panel.current?.focus());
          }}
        >
          While you were offline: 1 order filled, 1 stop moved by a rule.
        </Callout>
      ) : null}
    </section>
  );
}

export const Dismissible: Story = {
  render: () => <DismissHost />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await expect(canvas.getByRole("button", { name: "Dismiss Reconnected" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(canvas.getByRole("region", { name: "Orders panel" })).toHaveFocus());
    await expect(canvas.queryByRole("button", { name: "Dismiss Reconnected" })).toBeNull();
  },
};

/** The dismiss button's ring, drawn by the nested CMP-002 on the callout's fill. */
export const DismissFocusVisible: Story = {
  args: { title: "Reconnected", dismissible: true, onDismiss: fn() },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(
      within(canvasElement).getByRole("button", { name: "Dismiss Reconnected" }),
    ).toHaveFocus();
  },
};

/**
 * A protection-pending danger callout with its two actions, drawn with the solid edge every callout ships. This
 * is not the `unprotected` banner: its hatched edge (E30-D04 §2.3) is PROPOSED and deferred, so no story shows
 * it. Not dismissible while the stop is missing.
 */
export const ProtectionPendingSolidEdge: Story = {
  name: "Protection pending (solid edge; hatched edge deferred)",
  args: {
    tone: "danger",
    title: "Order live · protective stop pending — attaching the exchange stop (attempt 1 of 3)",
    children: undefined,
    actions: [
      { label: "Flatten now", onClick: fn() },
      { label: "Set stop by hand", onClick: fn() },
    ],
  },
};

/** A host's registered glyph replaces the tone's. */
export const CustomIcon: Story = {
  args: { icon: "lock", title: "Read-only: your role can't trade.", children: undefined },
};

/** Long words and many actions wrap; the actions wrap under the body. */
export const LongText: Story = {
  render: () => (
    <div style={{ ...col, width: "18rem" }}>
      <Callout
        tone="warning"
        title="Degraded — some data feeds are stale for BTCUSDT-PERPETUAL-LINEAR"
        live="off"
        retry={{ label: "Retry now", onClick: fn() }}
        actions={[
          { label: "Details", onClick: fn() },
          { label: "Open the connection panel", onClick: fn() },
        ]}
        dismissible
        onDismiss={fn()}
      >
        Book and tape are live; 1 of 4 topics stale 6s. Recent trades may lag.
      </Callout>
    </div>
  ),
};

/** Every tone and form under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => (
    <div style={col}>
      {TONES.map((t) => (
        <Callout
          key={t.tone}
          tone={t.tone}
          title={t.title}
          live="off"
          retry={{ label: "Retry now", onClick: fn() }}
          dismissible
          onDismiss={fn()}
        >
          {t.body}
        </Callout>
      ))}
      <Callout placement="band" title="Your access changed just now." live="off" />
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
