import type { Meta, StoryObj } from "@storybook/react-vite";
import { useCallback, useRef, useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { Dialog } from "./Dialog.js";
import { TextInput } from "./TextInput.js";
import {
  Toast,
  ToastRegion,
  type ToastAnnounce,
  type ToastItem,
  type ToastProps,
  type ToastRegionProps,
} from "./Toast.js";

/** The specimen board's cells (E05-D02 §CMP-045, board 08). */
const SESSION: ToastProps = {
  title: "Session extended",
  description: "Idle timer reset. Next warning in 14:00.",
};
const ACCEPTED: ToastProps = {
  tone: "success",
  kicker: "Success · Order",
  title: "Accepted — stop 63,900.0 held by the exchange",
};
const REASON = "Your role can't change alerts.";
const gate = (gated: boolean): { disabledReason?: string } =>
  gated ? { disabledReason: REASON } : {};
const alertActions = (gated: boolean): ToastProps["actions"] => [
  { label: "Open chart", onClick: fn() },
  { label: "Snooze", onClick: fn(), ...gate(gated) },
  { label: "Disable", onClick: fn(), ...gate(gated) },
  { label: "Details", onClick: fn(), variant: "ghost" },
];
const FIRED: ToastProps = {
  tone: "warning",
  kicker: "Warning · Alert",
  title: "BTC above 65k",
  description: "Last price 65,012.5 crossed above 65,000",
  meta: "BTCUSDT · 5m",
  actions: alertActions(false),
};
const REJECTED: ToastProps = {
  tone: "danger",
  kicker: "Danger · Order",
  title: "Order rejected — insufficient margin",
  description: "BTCUSDT buy 0.250 at 64,980.0 on Main was rejected by the exchange.",
  actions: [{ label: "Details", onClick: fn() }],
};

/** Theme and density come from the toolbars; every cell renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Toast> = {
  title: "Molecules/Toast",
  component: Toast,
  args: { ...SESSION, onDismiss: fn() },
};
export default meta;
type Story = StoryObj<typeof Toast>;

const col = { display: "grid", gap: "var(--space-stack-sm)", justifyItems: "start" } as const;

/** Default: Tone=info, timed, no action. A group named by its title, and never a live region itself. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("group", { name: "Session extended" });
    await expect(within(group).queryByRole("status")).toBeNull();
    const dismiss = within(group).getByRole("button", { name: "Dismiss Session extended" });
    // The entrance slides in from opacity 0 over `fast`.
    await waitFor(() => expect(dismiss).toBeVisible());
  },
};

/** The four tones: each with its glyph and its kicker word, never colour alone (H6: one overlay surface). */
export const AllTones: Story = {
  render: () => (
    <div style={col}>
      <Toast {...SESSION} kicker="Info · Session" onDismiss={fn()} />
      <Toast {...ACCEPTED} onDismiss={fn()} />
      <Toast {...FIRED} actions={undefined} onDismiss={fn()} />
      <Toast {...REJECTED} actions={undefined} onDismiss={fn()} />
    </div>
  ),
};

/** Success: E30-D02's accepted stop. */
export const Success: Story = { args: { ...ACCEPTED } };

/** WithAction: E40-D02's fired alert (Tone=warning, Action=actions); the body clamps to two lines. */
export const WithAction: Story = { args: { ...FIRED } };

/** Persistent: an order rejection (Tone=danger) with Details; it never times out in the region. */
export const Persistent: Story = { args: { ...REJECTED } };

/** PersistentLogLink: the record in the notification centre (SCR-014) as a ghost action. */
export const PersistentLogLink: Story = {
  args: {
    ...SESSION,
    actions: [{ label: "Open notifications", onClick: fn(), variant: "ghost" }],
  },
};

/** Focused: an action holds keyboard focus with its ring; in the region every timer is paused. */
export const Focused: Story = {
  args: { ...FIRED },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("button", { name: "Open chart" })).toHaveFocus();
  },
};

/** ActionGated: a viewer's fired alert. Snooze and Disable are T2 and both point at one reason line. */
export const ActionGated: Story = {
  args: { ...FIRED, actions: alertActions(true), onRefuse: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const snooze = canvas.getByRole("button", { name: "Snooze" });
    await expect(snooze).toHaveAttribute("aria-disabled", "true");
    await expect(snooze).toHaveAccessibleDescription(REASON);
    await expect(canvas.getByRole("button", { name: "Disable" })).toHaveAccessibleDescription(
      REASON,
    );
    await expect(canvasElement.querySelectorAll(".cv-toast__notice")).toHaveLength(1);
    snooze.focus();
    await userEvent.keyboard("{Enter}");
    await expect(args.onRefuse).toHaveBeenCalledWith(REASON);
  },
};

/** Undo: a local, reversible action (H27); its window open. */
export const Undo: Story = {
  args: {
    title: "EMA 21 removed",
    undo: { onUndo: fn(), outcome: "EMA 21 removed." },
  },
};

/** UndoOutcome: the window has closed; the outcome line replaces Undo and the toast stays. */
export const UndoOutcome: Story = {
  args: {
    title: "EMA 21 removed",
    undo: { onUndo: fn(), outcome: "EMA 21 removed." },
    undoClosed: true,
  },
};

/** LongText: the title keeps one line, the body clamps; the full text stays in the DOM. */
export const LongText: Story = {
  args: {
    tone: "warning",
    kicker: "Warning · Connection",
    title:
      "Market data for BTCUSDT, ETHUSDT and SOLUSDT is delayed while the public stream reconnects",
    description:
      "Book and tape are live for 3 of 6 topics. Charts keep the last bars; footprint and DOM heatmap pause until the stream is back. Recent trades may lag by several seconds.",
  },
};

/** The stories' local announcer pair, standing in for the shell's one pair (E17-D02 §11). */
function useLocalAnnouncer(): { announce: ToastAnnounce; regions: JSX.Element } {
  const polite = useRef<HTMLDivElement | null>(null);
  const assertive = useRef<HTMLDivElement | null>(null);
  const announce = useCallback<ToastAnnounce>((politeness, text) => {
    const region = politeness === "assertive" ? assertive.current : polite.current;
    if (region === null) return;
    region.textContent = "";
    region.append(document.createTextNode(text));
  }, []);
  return {
    announce,
    regions: (
      <>
        <div ref={polite} role="status" aria-live="polite" className="cv-visually-hidden" />
        <div ref={assertive} role="alert" aria-live="assertive" className="cv-visually-hidden" />
      </>
    ),
  };
}

let next = 0;
const make = (props: ToastProps): ToastItem => {
  next += 1;
  return { ...props, id: `toast-${next}` };
};

function RegionDemo({
  durationMs,
  withDialog = false,
}: Pick<ToastRegionProps, "durationMs"> & { readonly withDialog?: boolean }): JSX.Element {
  const { announce, regions } = useLocalAnnouncer();
  const [toasts, setToasts] = useState<readonly ToastItem[]>([]);
  const [open, setOpen] = useState(false);
  const push = (props: ToastProps): void => setToasts((list) => [...list, make(props)]);
  return (
    <div style={col}>
      {regions}
      <TextInput aria-label="Price" defaultValue="64,980.0" />
      <div style={{ display: "flex", gap: "var(--space-inset-sm)", flexWrap: "wrap" }}>
        <Button onClick={() => push(SESSION)}>Timed info</Button>
        <Button onClick={() => push(FIRED)}>Fired alert</Button>
        <Button onClick={() => push(REJECTED)}>Rejection</Button>
        <Button
          onClick={() =>
            push({ title: "EMA 21 removed", undo: { onUndo: fn(), outcome: "EMA 21 removed." } })
          }
        >
          Remove indicator
        </Button>
        {withDialog ? <Button onClick={() => setOpen(true)}>Open dialog</Button> : null}
      </div>
      {withDialog ? (
        <Dialog
          open={open}
          title="Rename layout"
          onOpenChange={setOpen}
          footer={<Button onClick={() => setOpen(false)}>Done</Button>}
        />
      ) : null}
      <ToastRegion
        toasts={toasts}
        announce={announce}
        onDismiss={(id) => setToasts((list) => list.filter((toast) => toast.id !== id))}
        {...(durationMs === undefined ? {} : { durationMs })}
      />
    </div>
  );
}

const body = within(document.body);

/**
 * Region: one portalled stack. Gherkin "Toast does not steal focus": focus stays in the typing field, the
 * sentence lands once in the polite region (danger in the assertive one). Hover or focus in the stack pauses
 * every timer; a toast with an action or `danger` never times out; `Esc` on a focused toast moves focus on.
 */
export const Region: Story = {
  render: () => <RegionDemo />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const field = canvas.getByRole("textbox", { name: "Price" });
    const fired = canvas.getByRole("button", { name: "Fired alert" });
    await userEvent.click(fired);
    await expect(fired).toHaveFocus();
    await userEvent.click(field);
    await userEvent.click(canvas.getByRole("button", { name: "Rejection" }));
    await userEvent.click(field);
    await expect(field).toHaveFocus();
    const region = await body.findByRole("region", { name: "Notifications" });
    await expect(within(region).getAllByRole("group")).toHaveLength(2);
    await waitFor(() => expect(canvas.getByRole("status")).toHaveTextContent("BTC above 65k"));
    await expect(canvas.getByRole("alert")).toHaveTextContent("Order rejected");
    const openChart = within(region).getByRole("button", { name: "Open chart" });
    openChart.focus();
    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(within(region).queryByRole("group", { name: "BTC above 65k" })).toBeNull(),
    );
    await expect(within(region).getByRole("button", { name: "Details" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(body.queryByRole("region", { name: "Notifications" })).toBeNull());
    await expect(field).toHaveFocus();
  },
};

/** RegionUntilDismissed: the user's "until dismissed" setting (`durationMs={null}`): no toast times out. */
export const RegionUntilDismissed: Story = {
  render: () => <RegionDemo durationMs={null} />,
};

/** RegionUnderModal: while a dialog is open the stack is inert and every timer in it is paused. */
export const RegionUnderModal: Story = {
  render: () => <RegionDemo withDialog />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Timed info" }));
    await userEvent.click(canvas.getByRole("button", { name: "Open dialog" }));
    const region = document.querySelector(".cv-toast-region");
    await waitFor(() => expect(region).toHaveAttribute("data-paused"));
    await expect(region?.hasAttribute("inert")).toBe(true);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(region).not.toHaveAttribute("data-paused"));
  },
};
