// @vitest-environment jsdom
import { createRequire } from "node:module";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, fn, within } from "storybook/test";
import { describe, it } from "vitest";
import { SymbolInfoPopover, type SymbolInfoPopoverProps } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

type Axe = {
  run: (context: object, options?: object) => Promise<{ violations: { impact?: string | null }[] }>;
};
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

const base: SymbolInfoPopoverProps = {
  symbol: "BTCUSDT",
  contract: {
    tickSize: "0.1",
    quantityStep: "0.001",
    minimumOrderValue: "5",
    maximumLeverage: "100×",
  },
  live: { last: "82,782.40", fundingRate: "+0.0100%" },
  recording: "Not recorded",
  onOpenFullDetails: () => undefined,
};

const dialog = (): HTMLElement => within(document.body).getByRole("dialog");
const click = async (el: Element): Promise<void> => {
  await act(async () => {
    fireEvent.click(el);
  });
};
const trigger = (host: HTMLElement): HTMLElement =>
  within(host).getByRole("button", { name: "Symbol info for BTCUSDT" });

describe("SymbolInfoPopover (CMP-125)", () => {
  it("opens only from its explicit trigger, named and aria-haspopup=dialog; never on hover", async () => {
    const host = await mount(<SymbolInfoPopover {...base} />);
    expect(trigger(host)).toHaveAttribute("aria-haspopup", "dialog");
    await act(async () => {
      fireEvent.mouseEnter(trigger(host));
      fireEvent.mouseOver(trigger(host));
    });
    expect(trigger(host)).toHaveAttribute("aria-expanded", "false");
    await click(trigger(host));
    expect(trigger(host)).toHaveAttribute("aria-expanded", "true");
    expect(dialog()).toHaveAccessibleName("BTCUSDT");
  });

  it("renders the three band sections in their fixed order, each named by its h3", async () => {
    await mount(<SymbolInfoPopover {...base} defaultOpen />);
    const headings = within(dialog()).getAllByRole("heading", { level: 3 });
    expect(headings.map((h) => h.textContent)).toEqual([
      "Contract rules",
      "Live market",
      "Recording in CandleViewer",
    ]);
    for (const name of ["Contract rules", "Live market", "Recording in CandleViewer"]) {
      expect(within(dialog()).getByRole("region", { name })).toBeTruthy();
    }
  });

  it("shows the host's formatted values as given", async () => {
    await mount(<SymbolInfoPopover {...base} defaultOpen />);
    const d = within(dialog());
    for (const text of ["Tick size", "0.1", "Quantity step", "0.001", "Minimum order value", "5"])
      expect(d.getByText(text)).toBeTruthy();
    for (const text of [
      "Maximum leverage",
      "100×",
      "Last",
      "82,782.40",
      "Funding rate",
      "+0.0100%",
    ])
      expect(d.getByText(text)).toBeTruthy();
    expect(d.getByText("Not recorded")).toBeTruthy();
  });

  it("an absent value is 'not available', never a zero or an empty cell", async () => {
    await mount(
      <SymbolInfoPopover
        {...base}
        contract={{ tickSize: "0.1" }}
        live={{}}
        recording={undefined}
        defaultOpen
      />,
    );
    expect(within(dialog()).getAllByText("not available").length).toBe(6);
    expect(dialog().textContent).not.toMatch(/\b0\b(?!\.)/);
  });

  it("stale: the marker is in the live band only; the contract band has none", async () => {
    await mount(<SymbolInfoPopover {...base} state="stale" staleAgeMs={7_000} defaultOpen />);
    const live = within(dialog()).getByRole("region", { name: "Live market" });
    expect(within(live).getByText("Stale, 7 seconds")).toBeTruthy();
    const contract = within(dialog()).getByRole("region", { name: "Contract rules" });
    expect(contract.querySelector("[data-cmp='CMP-239']")).toBeNull();
  });

  it("not trading: the status heading replaces the live rows", async () => {
    await mount(
      <SymbolInfoPopover
        {...base}
        state="not-trading"
        notTradingHeading="BTCUSDT is not trading on Bybit."
        defaultOpen
      />,
    );
    expect(within(dialog()).getByText("BTCUSDT is not trading on Bybit.")).toBeTruthy();
    expect(within(dialog()).queryByText("Last")).toBeNull();
    expect(within(dialog()).getByText("Tick size")).toBeTruthy();
  });

  it("unavailable: the sentence and the action, no rows and no bands", async () => {
    await mount(<SymbolInfoPopover {...base} state="unavailable" defaultOpen />);
    expect(within(dialog()).getByText("Contract rules not loaded")).toBeTruthy();
    expect(within(dialog()).queryAllByRole("heading", { level: 3 })).toEqual([]);
    expect(within(dialog()).getByRole("button", { name: "Open full details" })).toBeTruthy();
  });

  it("'Open full details' calls the host once", async () => {
    const onOpenFullDetails = fn();
    await mount(<SymbolInfoPopover {...base} onOpenFullDetails={onOpenFullDetails} defaultOpen />);
    await click(within(dialog()).getByRole("button", { name: "Open full details" }));
    expect(onOpenFullDetails).toHaveBeenCalledTimes(1);
  });

  it("Esc closes it and returns focus to the trigger", async () => {
    function Host(): JSX.Element {
      const [open, setOpen] = useState(false);
      return <SymbolInfoPopover {...base} open={open} onOpenChange={setOpen} />;
    }
    const host = await mount(<Host />);
    await click(trigger(host));
    expect(trigger(host)).toHaveAttribute("aria-expanded", "true");
    await act(async () => {
      fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    });
    expect(trigger(host)).toHaveAttribute("aria-expanded", "false");
    expect(trigger(host)).toHaveFocus();
  });

  it("Tab order inside the open popover reaches its one action", async () => {
    await mount(<SymbolInfoPopover {...base} defaultOpen />);
    const buttons = within(dialog()).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Open full details"]);
  });

  it.each(["default", "stale", "not-trading", "unavailable"] as const)(
    "axe: the %s state has no serious or critical violation",
    async (state) => {
      await mount(
        <SymbolInfoPopover
          {...base}
          state={state}
          staleAgeMs={7_000}
          notTradingHeading="BTCUSDT is not trading on Bybit."
          defaultOpen
        />,
      );
      const { violations } = await axe.run(
        { include: [dialog()] },
        { rules: { "color-contrast": { enabled: false } } },
      );
      expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
        [],
      );
    },
  );
});
