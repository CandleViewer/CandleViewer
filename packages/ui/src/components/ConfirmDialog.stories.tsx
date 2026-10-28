import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { ConfirmDialog, type ConfirmDialogProps, type ConfirmMeta } from "./ConfirmDialog.js";

const column = { display: "flex", flexDirection: "column", gap: "var(--space-stack-sm)" } as const;

/** A story clock the play functions move, so the 400 ms guard is tested without waiting on wall time. */
const clock = { t: 0 };
const storyNow = (): number => clock.t;

type DemoProps = Partial<Omit<ConfirmDialogProps, "open" | "onConfirm" | "onCancel">> & {
  opener?: string;
  /** Keep the dialog open after Confirm (busy and failure stories); otherwise the host closes it. */
  stayOpen?: boolean;
};

/** The opener and the host's outcome line; the confirm opens from the button (focus returns there). */
function Demo({ opener = "Freeze sub_001", stayOpen = false, ...props }: DemoProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState("Nothing sent.");
  return (
    <div style={column}>
      <div>
        <Button variant="danger" onClick={() => setOpen(true)}>
          {opener}
        </Button>
      </div>
      <p style={{ margin: 0 }} data-testid="outcome">
        {outcome}
      </p>
      <ConfirmDialog
        open={open}
        title="Freeze sub_001?"
        message="sub_001 stops taking new orders until you unfreeze it."
        restatement={
          <>
            <p>Cancels 3 working orders on sub_001.</p>
            <p>
              <strong>Open positions are NOT closed.</strong>
            </p>
          </>
        }
        confirmLabel="Freeze sub_001 — cancel 3 working orders"
        onConfirm={(meta: ConfirmMeta) => {
          setOutcome(
            `Confirmed: ${meta.variant}, ${meta.gate}, after ${String(meta.elapsedMs)} ms.`,
          );
          if (!stayOpen) setOpen(false);
        }}
        onCancel={(reason) => {
          setOutcome(`Cancelled (${reason}). Nothing sent.`);
          setOpen(false);
        }}
        {...props}
      />
    </div>
  );
}

const meta: Meta = {
  title: "Molecules/ConfirmDialog",
  component: ConfirmDialog,
  render: () => <Demo />,
};
export default meta;
type Story = StoryObj;

const page = within(document.body);
const opened = async (canvas: HTMLElement, name = "Freeze sub_001"): Promise<HTMLElement> => {
  const opener = within(canvas).getByRole("button", { name });
  await userEvent.click(opener);
  await waitFor(() => expect(document.querySelector(".cv-dialog")).not.toBeNull());
  return opener;
};
const closed = async (): Promise<void> =>
  waitFor(() => expect(document.querySelector(".cv-dialog-layer")).toBeNull());

/** Variant=standard, State=default: SCR-072's freeze; focus on Cancel, Tab to Confirm, Esc cancels. */
export const Standard: Story = {
  play: async ({ canvasElement }) => {
    const opener = await opened(canvasElement);
    const dialog = page.getByRole("alertdialog", { name: "Freeze sub_001?" });
    await expect(dialog).toHaveAttribute("aria-modal", "true");
    await expect(within(dialog).getByRole("group", { name: "What this does" })).toBeVisible();
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    await expect(cancel).toHaveFocus();
    await userEvent.tab();
    await expect(
      within(dialog).getByRole("button", { name: /^Freeze sub_001 — cancel/ }),
    ).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await closed();
    await expect(opener).toHaveFocus();
    await expect(within(canvasElement).getByTestId("outcome")).toHaveTextContent(
      "Cancelled (escape)",
    );
  },
};

/** The guard: a click and an Enter inside the first 400 ms do nothing; after it, one press confirms. */
export const Guard: Story = {
  render: () => <Demo now={storyNow} />,
  play: async ({ canvasElement }) => {
    clock.t = 0;
    await opened(canvasElement);
    const confirm = page.getByRole("button", { name: /^Freeze sub_001 — cancel/ });
    clock.t = 150;
    await userEvent.click(confirm);
    confirm.focus();
    clock.t = 399;
    await userEvent.keyboard("{Enter}");
    await expect(page.getByRole("alertdialog")).toBeVisible();
    clock.t = 650;
    await userEvent.keyboard("{Enter}");
    await closed();
    await expect(within(canvasElement).getByTestId("outcome")).toHaveTextContent(
      "Confirmed: standard, click, after 650 ms.",
    );
  },
};

/** Variant=typed: E42-D02's rung 3; the field empty, Confirm natively disabled. */
export const Typed: Story = {
  render: () => (
    <Demo
      opener="Remove alex"
      title="Delete user alex?"
      message="alex loses access to every account at once."
      restatement={<p>Removes alex, their sessions and their two API keys.</p>}
      confirmLabel="Delete user alex"
      variant="typed"
      typedConfirmValue="alex"
      typedInstruction="Type alex to delete this user"
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Remove alex");
    const confirm = page.getByRole("button", { name: "Delete user alex" });
    await expect(confirm).toBeDisabled();
    await expect(confirm).toHaveAccessibleDescription("Type alex to delete this user");
  },
};

/** Gherkin "Typed confirm": with FLATTEN required, any other text keeps Confirm disabled; a match enables it. */
export const TypedMatch: Story = {
  render: () => (
    <Demo
      opener="Flatten all"
      title="Flatten all positions?"
      message="4 positions across 2 accounts, LIVE and DEMO."
      restatement={<p>Closes 4 positions at market and cancels 9 working orders.</p>}
      confirmLabel="Flatten 4 positions — all accounts"
      variant="typed"
      typedConfirmValue="FLATTEN"
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Flatten all");
    const field = page.getByRole("textbox", { name: "Type FLATTEN to confirm" });
    const confirm = page.getByRole("button", { name: "Flatten 4 positions — all accounts" });
    await userEvent.type(field, "flatten");
    await expect(confirm).toBeDisabled();
    await userEvent.clear(field);
    await userEvent.type(field, "FLATTEN{Enter}");
    await expect(page.getByRole("alertdialog")).toBeVisible();
    await expect(confirm).toBeEnabled();
  },
};

/** State=busy: after Confirm, CMP-001 loading, the field read-only, aria-busy on the card. */
export const Busy: Story = {
  render: () => (
    <Demo
      busy
      variant="typed"
      typedConfirmValue="FLATTEN"
      confirmLabel="Flatten 4 positions"
      opener="Flatten all"
      title="Flatten all positions?"
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Flatten all");
    await expect(page.getByRole("alertdialog")).toHaveAttribute("aria-busy", "true");
    await expect(page.getByRole("textbox", { name: "Type FLATTEN to confirm" })).toHaveAttribute(
      "readonly",
    );
  },
};

/** State=partial-failure: SCR-072's "partial failure with retry" through CMP-027. */
export const PartialFailure: Story = {
  render: () => (
    <Demo
      stayOpen
      failure={{
        message: "2 of 3 orders were not cancelled. sub_001 is frozen.",
        retry: { label: "Retry", onClick: () => undefined },
      }}
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    const dialog = page.getByRole("alertdialog");
    await expect(within(dialog).getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(within(dialog).getByText(/2 of 3 orders/)).toBeVisible();
  },
};

/** State=gated (H30): the leg removed mid-dialog; Confirm in CMP-001's T2 form, the reason under the footer. */
export const ConfirmGated: Story = {
  render: () => (
    <Demo
      opener="Kill switch"
      title="Engage the kill switch?"
      restatement={<p>Cancels every working order and blocks new ones on all accounts.</p>}
      confirmLabel="Engage the kill switch"
      confirmDisabledReason="Your role can't use the kill switch."
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Kill switch");
    const confirm = page.getByRole("button", { name: /^Engage the kill switch/ });
    await expect(confirm).toHaveAttribute("aria-disabled", "true");
    await expect(confirm).toHaveAccessibleDescription("Your role can't use the kill switch.");
    confirm.focus();
    await userEvent.keyboard("{Enter}");
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    await expect(within(dialog).getByRole("status")).toHaveTextContent(
      "Your role can't use the kill switch.",
    );
  },
};

/** An order confirm (SCR-076): a dialog with its close button; Tab runs Cancel, Confirm, close, the body. */
export const OrderConfirm: Story = {
  render: () => (
    <Demo
      opener="Review order"
      role="dialog"
      aria-label="Confirm order - BTCUSDT - LIVE - Main"
      title="Confirm order"
      restatementLabel=""
      restatement={
        <>
          <p>LIVE on Main. Real funds.</p>
          <p>
            <strong>BUY 0.250 BTCUSDT limit 64,010.0 · stop 63,900.0</strong>
          </p>
        </>
      }
      confirmVariant="buy"
      confirmLabel="BUY 0.250 BTCUSDT limit 64,010.0 · stop 63,900.0"
      variant="typed"
      typedConfirmValue="LIVE"
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "Review order");
    const dialog = page.getByRole("dialog", { name: "Confirm order - BTCUSDT - LIVE - Main" });
    const field = within(dialog).getByRole("textbox", { name: "Type LIVE to confirm" });
    await userEvent.type(field, "LIVE");
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    cancel.focus();
    await userEvent.tab();
    await expect(within(dialog).getByRole("button", { name: /^BUY 0.250/ })).toHaveFocus();
    await userEvent.tab();
    await expect(within(dialog).getByRole("button", { name: "Close Confirm order" })).toHaveFocus();
    await userEvent.tab();
    await expect(field).toHaveFocus();
    await userEvent.tab();
    await expect(cancel).toHaveFocus();
  },
};

/** Long text: a long title, restatement and effect label wrap; the footer wraps (conventions 39). */
export const LongText: Story = {
  render: () => (
    <Demo
      title="Cancel all working orders on sub_001, sub_002 and sub_003 across BTCUSDT, ETHUSDT and SOLUSDT?"
      restatement={
        <p>
          Cancels 27 working orders, including 6 protective stops, on three accounts; positions stay
          open and unprotected until you place new stops.
        </p>
      }
      confirmLabel="Cancel 27 working orders on 3 accounts, including 6 protective stops"
      cancelLabel="Keep my orders"
    />
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await expect(page.getByRole("button", { name: "Keep my orders" })).toHaveFocus();
  },
};

const themed = (theme: string): Story => ({
  globals: { theme },
  render: () => <Demo variant="typed" typedConfirmValue="FLATTEN" />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await opened(canvasElement);
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
