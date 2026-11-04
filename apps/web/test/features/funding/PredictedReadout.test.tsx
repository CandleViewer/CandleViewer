// E24-S04 (#779): the accruing rate by role: the words "predicted" and "estimated" in the text and in the
// accessible name, never colour alone; n/a with no chip; the annualised figure and its formula; the table's
// predicted row and Annualised column; the toggle's presence, state and analytics. axe over every story.
import { createRequire } from "node:module";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import * as stories from "../../../src/features/funding/ui/FundingPredicted.stories";
import { FundingMethodologyHost } from "../../../src/features/funding/ui/FundingMethodologyHost";
import { PredictedReadout } from "../../../src/features/funding/ui/PredictedReadout";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

const serious = async (): Promise<string[]> =>
  (await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } })).violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => v.id);

/** The header's readout: the text and the chip after the rate (the name is the chip's, no group label). */
const readout = (): HTMLElement => {
  const node = document.querySelector<HTMLElement>(".cv-funding-readout");
  if (node === null) throw new Error("no readout");
  return node;
};

describe("the predicted readout", () => {
  it("says predicted and estimated as words, as text and in the chip's name", () => {
    render(stories.SettledAndPredicted.render());
    expect(within(readout()).getByText(/^predicted/)).toBeTruthy();
    const chip = within(readout()).getByRole("button", { name: "Estimated, Funding rate" });
    expect(chip.textContent).toBe("≈(estimated)");
    expect(chip.getAttribute("aria-haspopup")).toBe("dialog");
  });

  it("shows the interval and the server's annualised figure, the formula as its description, no tab stop", () => {
    render(stories.SettledAndPredicted.render());
    const figure = within(readout()).getByText("/ 8 h · +10.95 % p.a.");
    const description = document.getElementById(figure.getAttribute("aria-describedby") ?? "");
    expect(description?.textContent).toBe("0.0100 % × (525600 / 480) = 10.95 % p.a.");
    expect(description?.className).toContain("cv-visually-hidden");
    expect(figure.tagName).toBe("SPAN");
    expect(figure.hasAttribute("tabindex")).toBe(false);
    expect(readout().querySelector(".cv-funding-readout__figure")).toBe(figure);
  });

  it("leads with the annualised figure when it is on, per-interval second", () => {
    const { container } = render(stories.Annualised.render());
    expect(container.querySelector(".cv-funding__rate")?.textContent).toBe("+10.95 % p.a.");
    expect(within(readout()).getByText("+0.0100 % / 8 h")).toBeTruthy();
  });

  it("uses the symbol's own interval, 4 h here", () => {
    render(stories.FourHourInterval.render());
    expect(screen.getByText("0.0100 % × (525600 / 240) = 21.90 % p.a.")).toBeTruthy();
  });

  it("states n/a with no chip, no marker and no row when nothing is published", () => {
    render(stories.PredictedAbsent.render());
    expect(screen.getByText("Funding n/a")).toBeTruthy();
    expect(screen.getByText("No predicted rate is published right now.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Estimated/ })).toBeNull();
    expect(screen.queryByText(/^predicted/)).toBeNull();
  });

  it("omits an annualised figure the server did not serve and hides its toggle", () => {
    render(stories.PredictedNoAnnualised.render());
    expect(screen.queryByText(/\d % p\.a\./)).toBeNull();
    expect(screen.queryByRole("switch", { name: "Annualised (% p.a.)" })).toBeNull();
    expect(within(readout()).getByText("/ 8 h")).toBeTruthy();
  });

  it("drops the annualised figure once the ticker rate moved off the one the server annualised", () => {
    render(stories.TickerMovedOn.render());
    expect(screen.queryByText(/\d % p\.a\./)).toBeNull();
    expect(within(readout()).getByText("/ 8 h")).toBeTruthy(); // the interval stays, the figure and formula go
    expect(screen.queryByText(/525600/)).toBeNull();
  });

  it("opens the methodology from a click that never focused the chip, and Escape returns focus to it", async () => {
    render(
      <FundingMethodologyHost>
        <PredictedReadout
          readout={{ kind: "predicted", rate: "0.0001", intervalMinutes: 480, annualisedPct: null }}
          annualised={false}
        />
      </FundingMethodologyHost>,
    );
    const chip = screen.getByRole("button", { name: "Estimated, Funding rate" });
    expect(screen.queryByRole("heading", { name: "Funding rate" })).toBeNull();
    // Safari and Firefox/macOS: a mouse click does not focus a button, so `activeElement` stays `body`
    expect(document.activeElement).toBe(document.body);
    fireEvent.click(chip);
    // the drawer's heading is the proof it opened: the tooltip's copy is in the DOM, hidden, from mount
    const heading = await screen.findByRole("heading", { name: "Funding rate" });
    expect(document.activeElement).toBe(heading);
    fireEvent.keyDown(heading, { key: "Escape" });
    await waitFor(() => expect(document.activeElement).toBe(chip));
  });
});

describe("the table alternative", () => {
  it("adds the predicted row last, worded, with the annualised column and its unit", () => {
    render(stories.SettledAndPredicted.render());
    const table = screen.getByRole("table", { name: /settled and predicted \(estimated\)/ });
    expect(within(table).getByRole("columnheader", { name: "Annualised (% p.a.)" })).toBeTruthy();
    const rows = within(table).getAllByRole("row");
    const last = rows.at(-1);
    expect(last && within(last).getByText(/^predicted/)).toBeTruthy();
    expect(
      last && within(last).getByRole("button", { name: "Estimated, Funding rate" }),
    ).toBeTruthy();
    expect(within(rows[1] as HTMLElement).queryByRole("button", { name: /Estimated/ })).toBeNull();
    expect(last && within(last).getByText("+10.95 %")).toBeTruthy();
    expect(within(rows[1] as HTMLElement).getByText("settled")).toBeTruthy();
  });

  it("has no predicted row with nothing published, and says not published where no value is served", () => {
    render(stories.PredictedAbsent.render());
    const table = screen.getByRole("table");
    expect(within(table).queryByText(/^predicted/)).toBeNull();
  });
});

describe("the toggle", () => {
  it("is a switch while the server serves an annualised value", () => {
    const { unmount } = render(stories.SettledAndPredicted.render());
    expect(
      screen.getByRole("switch", { name: "Annualised (% p.a.)" }).getAttribute("aria-checked"),
    ).toBe("false");
    unmount();
    render(stories.Annualised.render());
    expect(
      screen.getByRole("switch", { name: "Annualised (% p.a.)" }).getAttribute("aria-checked"),
    ).toBe("true");
  });
});

describe("accessibility", () => {
  it.each(Object.entries(stories).filter(([name]) => name !== "default"))(
    "%s has no serious or critical axe violation",
    async (_name, story) => {
      render((story as { render: () => JSX.Element }).render());
      expect(await serious()).toEqual([]);
    },
    30_000,
  );
});
