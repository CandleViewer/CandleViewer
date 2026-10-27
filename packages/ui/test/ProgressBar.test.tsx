// @vitest-environment jsdom
import { describe, it } from "vitest";
import { expect, within } from "storybook/test";
import { ProgressBar } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

describe("ProgressBar (CMP-023)", () => {
  it("is a progressbar named by its visible label, with value, range and value text", async () => {
    const host = await mount(
      <ProgressBar label="Loading history" value={33} valueText="page 3 of ~9" />,
    );
    const bar = within(host).getByRole("progressbar", { name: "Loading history" });
    expect(bar).toHaveAttribute("aria-valuenow", "33");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(bar).toHaveAttribute("aria-valuetext", "page 3 of ~9");
    expect(within(host).getByText("page 3 of ~9")).toHaveAttribute("aria-hidden", "true");
    expect(host.querySelector("[data-cmp='CMP-023']")).toHaveAttribute("data-tone", "default");
    expect(bar).not.toHaveAttribute("aria-live");
    expect(host.querySelector("[role='status'], [role='alert'], [aria-live]")).toBeNull();
  });

  it("kind meter renders role meter and reads the percent sign", async () => {
    const host = await mount(<ProgressBar kind="meter" label="Recording budget" value={31} />);
    expect(within(host).getByRole("meter")).toHaveAttribute("aria-valuetext", "31 %");
    expect(within(host).getByRole("meter", { name: "Recording budget" })).toHaveAttribute(
      "aria-valuenow",
      "31",
    );
    expect(within(host).queryByRole("progressbar")).toBeNull();
  });

  it("without valueText shows the percentage and reads it as aria-valuetext", async () => {
    const host = await mount(<ProgressBar label="Export" value={42.4} />);
    expect(within(host).getByRole("progressbar")).toHaveAttribute("aria-valuetext", "42 %");
    expect(within(host).getByText("42 %")).toBeTruthy();
  });

  it("clamps the value to 0–100 and treats a non-finite value as 0", async () => {
    const now = async (value: number): Promise<string | null> =>
      within(await mount(<ProgressBar label="X" value={value} />))
        .getByRole("progressbar")
        .getAttribute("aria-valuenow");
    expect(await now(-5)).toBe("0");
    expect(await now(140)).toBe("100");
    expect(await now(Number.NaN)).toBe("0");
  });

  it("the fill scale follows the value", async () => {
    const host = await mount(<ProgressBar label="X" value={25} />);
    const fill = host.querySelector<HTMLElement>(".cv-progress__fill");
    expect(fill?.style.getPropertyValue("--cv-progress")).toBe("0.25");
  });

  it("warning and danger carry a decorative glyph before the value text; other tones none", async () => {
    for (const tone of ["warning", "danger"] as const) {
      const host = await mount(<ProgressBar label="Disk" kind="meter" tone={tone} value={90} />);
      const svg = host.querySelector(".cv-progress__value > svg");
      expect(svg, tone).not.toBeNull();
      expect(svg?.closest("[aria-hidden='true']")).not.toBeNull();
      expect(within(host).getByRole("meter")).toHaveAccessibleName("Disk");
    }
    for (const tone of ["default", "success"] as const) {
      const host = await mount(<ProgressBar label="Disk" tone={tone} value={90} />);
      expect(host.querySelector(".cv-progress__value > svg"), tone).toBeNull();
    }
  });

  it("is named by aria-labelledby, and a name is required by the type", async () => {
    const host = await mount(
      <>
        <h3 id="hdr">Exporting trades</h3>
        <ProgressBar aria-labelledby="hdr" value={60} />
      </>,
    );
    expect(within(host).getByRole("progressbar")).toHaveAccessibleName("Exporting trades");
    expect(host.querySelector(".cv-progress__label")).toBeNull();
    expect(within(host).getByText("60 %")).toBeTruthy();
    // @ts-expect-error a bar with no accessible name must not compile
    const nameless = <ProgressBar value={1} />;
    // @ts-expect-error label and aria-labelledby are exclusive
    const both = <ProgressBar value={1} label="A" aria-labelledby="hdr" />;
    expect([nameless, both]).toHaveLength(2);
  });
});
