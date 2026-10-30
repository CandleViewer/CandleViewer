import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type FormEvent, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { ErrorState, InlineError } from "./ErrorState.js";

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof ErrorState> = {
  title: "Atoms/ErrorState",
  component: ErrorState,
  args: { message: "Couldn't load users — store unavailable.", severity: "error", form: "panel" },
};
export default meta;
type Story = StoryObj<typeof ErrorState>;

const col = { display: "grid", gap: "var(--space-stack-md)", maxWidth: "40rem" } as const;

/** Error: the `error` glyph, `role="alert"` (a transient failure), filled after mount so it is read once. */
export const ErrorSeverityStory: Story = {
  name: "Error",
  play: async ({ canvasElement }) => {
    const alert = await within(canvasElement).findByRole("alert");
    await expect(alert).toHaveAttribute("aria-live", "assertive");
    await expect(alert).toHaveTextContent("store unavailable");
  },
};

/** Warning: the `warning` glyph and the host's sentence, `role="status"`. */
export const Warning: Story = {
  args: { severity: "warning", message: "Some history is missing for this range." },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("status")).toHaveTextContent("history is missing");
    await expect(canvas.queryByRole("alert")).toBeNull();
  },
};

/** An in-panel load failure is polite (H14): the default cell, with Retry outside the region. */
export const WithRetry: Story = {
  args: { live: "polite", retry: { label: "Retry", onClick: fn() } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const status = await canvas.findByRole("status");
    await expect(status).not.toHaveTextContent("Retry");
    await userEvent.tab();
    await expect(canvas.getByRole("button", { name: "Retry" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(args.retry?.onClick).toHaveBeenCalledTimes(1);
  },
};

/** The Polite story: `live="polite"` over the error default. */
export const Polite: Story = {
  args: { live: "polite" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("status")).toHaveTextContent("store unavailable");
    await expect(canvas.queryByRole("alert")).toBeNull();
  },
};

/** "Technical details" opens: the code and the correlation id, selectable, with a CMP-033 copy. */
export const WithDetails: Story = {
  args: {
    live: "polite",
    retry: { label: "Retry", onClick: fn() },
    details: "code: STORE_UNAVAILABLE\ncorrelation: 7f3c2a91",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = canvas.getByRole("button", { name: "Technical details" });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByRole("button", { name: "Copy technical details" })).toBeVisible();
    // The open box holds CMP-033's own status; neither region ever carries the details.
    await canvas.findByText("Couldn't load users — store unavailable.");
    for (const region of canvas.getAllByRole("status")) {
      await expect(region).not.toHaveTextContent("STORE_UNAVAILABLE");
    }
  },
};

/** Inline: the refusal at the point of action, one row, assertive once. */
export const Inline: Story = {
  render: () => (
    <InlineError message="Not sent — your access changed. Ask the owner to restore trading." />
  ),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("Not sent");
  },
};

/** Inline with an inline Retry. */
export const InlineWithRetry: Story = {
  render: () => (
    <InlineError
      message="Couldn't save the layout."
      live="polite"
      retry={{ label: "Retry", onClick: fn() }}
    />
  ),
};

/** Banner: a rejected order's class line in CMP-028's box, the message strong, `role="alert"` once. */
export const Banner: Story = {
  args: { form: "banner", message: "Not sent — the price is off-tick." },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("off-tick");
  },
};

/** The warning banner. */
export const BannerWarning: Story = {
  args: { form: "banner", severity: "warning", message: "Price is far from the last trade." },
};

/**
 * Focuses the summary's heading on the first frame it exists, within about a second. ErrorState renders its
 * words, the heading among them, one effect after it mounts, so the frame after the submit can come first.
 */
const focusHeading = (frames = 60): void => {
  requestAnimationFrame(() => {
    const heading = document.getElementById("summary-heading");
    if (heading !== null) heading.focus();
    else if (frames > 1) focusHeading(frames - 1);
  });
};

/** E30-D02 D16's error summary: the host moves focus to the heading; a link moves focus to its field. */
function SummaryHost(): JSX.Element {
  const [failed, setFailed] = useState(false);
  const submit = (event: FormEvent): void => {
    event.preventDefault();
    setFailed(true);
    focusHeading();
  };
  return (
    <form onSubmit={submit} style={col} noValidate>
      {failed ? (
        <ErrorState
          form="banner"
          title="Can't submit — 2 problems"
          headingId="summary-heading"
          message="Fix these and submit again."
          items={[
            { label: "Enter a quantity", href: "#qty" },
            { label: "Enter a stop-loss", href: "#stop" },
          ]}
        />
      ) : null}
      <label htmlFor="qty">Quantity</label>
      <input id="qty" />
      <label htmlFor="stop">Stop-loss</label>
      <input id="stop" />
      <button type="submit">Submit</button>
    </form>
  );
}

export const Summary: Story = {
  render: () => <SummaryHost />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Submit" }));
    const heading = await canvas.findByRole("heading", { name: "Can't submit — 2 problems" });
    await waitFor(() => expect(heading).toHaveFocus());
    await expect(canvas.getByRole("alert")).toContainElement(heading);
    await userEvent.click(canvas.getByRole("link", { name: "Enter a stop-loss" }));
    await expect(canvas.getByLabelText("Stop-loss")).toHaveFocus();
  },
};

/** `off`: another node already announced it; no live role. */
export const LiveOff: Story = {
  args: { live: "off", form: "inline", message: "Not sent — the price is off-tick." },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("alert")).toBeNull();
    await expect(canvas.queryByRole("status")).toBeNull();
  },
};

/** Long words wrap; the details scroll inside their box and never truncate. */
export const LongText: Story = {
  render: () => (
    <div style={{ ...col, width: "18rem" }}>
      <ErrorState
        live="off"
        title="Couldn't load BTCUSDT-PERPETUAL-LINEAR-DEMO-ACCOUNT-SUBACCOUNT-7"
        message="The market-data store did not answer in time; the panel keeps its last good snapshot."
        retry={{ label: "Retry", onClick: fn() }}
        action={{ label: "Open the connection panel", onClick: fn() }}
        details="code: STORE_UNAVAILABLE correlation: 7f3c2a91-0b7d-4f7e-9c1d-2e5a8f6b4c3d"
      />
      <InlineError live="off" message="Not sent — your access changed while the order was open." />
      <ErrorState
        live="off"
        form="banner"
        message="Not sent — the quantity is below the instrument's minimum order size."
      />
    </div>
  ),
};

/** Every form and severity under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => (
    <div style={col}>
      {(["error", "warning"] as const).map((severity) => (
        <div key={severity} style={col}>
          <ErrorState
            live="off"
            severity={severity}
            message="Couldn't load users — store unavailable."
            retry={{ label: "Retry", onClick: fn() }}
            details="code: STORE_UNAVAILABLE"
          />
          <InlineError live="off" severity={severity} message="Not sent — your access changed." />
          <ErrorState
            live="off"
            form="banner"
            severity={severity}
            title="Can't submit — 1 problem"
            message="Fix it and submit again."
            items={[{ label: "Enter a quantity", href: "#qty" }]}
          />
        </div>
      ))}
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
