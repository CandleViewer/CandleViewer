// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, expectTypeOf, it } from "vitest";
import { PrintExportBar, type PrintExportBarProps } from "../src/components/index.js";
import * as stories from "../src/components/PrintExportBar.stories.js";
import { seriousViolations } from "./axe.js";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";
import { mount } from "./theme/mount.js";

const exportCsv = (host: HTMLElement): HTMLElement =>
  within(host).getByRole("button", { name: "Export CSV" });

describe("PrintExportBar (CMP-099, E29-S04; E29-D04 §2.8.9)", () => {
  it("draws CSV alone as one CMP-001 secondary button named by the design's words, Export CSV", async () => {
    const host = await mount(<PrintExportBar formats={["csv"]} onExport={fn()} />);
    const button = exportCsv(host);
    expect(within(host).getAllByRole("button")).toHaveLength(1);
    expect(button.tagName).toBe("BUTTON");
    expect(button).toHaveAttribute("type", "button");
    expect([button.dataset["cmp"], button.dataset["variant"]]).toEqual(["CMP-001", "secondary"]);
    expect(host.querySelectorAll('[data-cmp="CMP-099"]')).toHaveLength(1);
  });

  it("gives each format its own labelled button in the host's order, a repeated one once", async () => {
    const host = await mount(<PrintExportBar formats={["pdf", "csv", "pdf"]} onExport={fn()} />);
    expect(
      within(host)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Export PDF", "Export CSV"]);
  });

  it("is keyboard operable: Tab reaches Export CSV, and Enter and Space each start the export", async () => {
    const onExport = fn();
    const host = await mount(<PrintExportBar formats={["csv", "pdf"]} onExport={onExport} />);
    await userEvent.tab();
    expect(exportCsv(host)).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(onExport.mock.calls).toEqual([["csv"], ["csv"], ["pdf"]]);
  });

  it("a pointer press starts the export of its own format", async () => {
    const onExport = fn();
    const host = await mount(<PrintExportBar formats={["csv"]} onExport={onExport} />);
    await userEvent.click(exportCsv(host));
    expect(onExport.mock.calls).toEqual([["csv"]]);
  });

  it("running keeps the label as the name with aria-busy, and a press does nothing (E29-D03:200)", async () => {
    const onExport = fn();
    const host = await mount(<PrintExportBar formats={["csv"]} onExport={onExport} loading />);
    const button = exportCsv(host);
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button.querySelector(".cv-button__label")).toHaveTextContent("Export CSV");
    expect(button.querySelector(".cv-spinner")).toHaveAttribute("aria-hidden", "true");
    await userEvent.tab();
    expect(button).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    await userEvent.click(button);
    expect(onExport).not.toHaveBeenCalled();
  });

  it("busy is never T2: no aria-disabled, no disabled, no lock and no reason (E29-D04:391)", async () => {
    const host = await mount(<PrintExportBar formats={["csv"]} onExport={fn()} loading />);
    const button = exportCsv(host);
    expect(button).not.toHaveAttribute("aria-disabled");
    expect(button).not.toBeDisabled();
    expect(button).not.toHaveAttribute("aria-describedby");
    expect(host.querySelector("svg[aria-label], [data-gated]")).toBeNull();
  });

  it("has no live region of its own: the host's footer speaks the export's progress and result", async () => {
    const host = await mount(<PrintExportBar formats={["csv"]} onExport={fn()} loading />);
    expect(host.querySelector("[aria-live], [role='status'], [role='alert']")).toBeNull();
  });

  it("emits the density on the bar and on each button", async () => {
    const host = await mount(
      <PrintExportBar formats={["csv"]} onExport={fn()} density="comfortable" />,
    );
    const bar = host.querySelector<HTMLElement>('[data-cmp="CMP-099"]');
    expect([bar?.dataset["density"], exportCsv(host).dataset["density"]]).toEqual([
      "comfortable",
      "comfortable",
    ]);
  });

  it("the type-level contract: at least one format, and only CSV or PDF (tsc checks this file)", () => {
    const onExport = (): void => undefined;
    expectTypeOf({ formats: ["csv"], onExport } as const).toExtend<PrintExportBarProps>();
    expectTypeOf({ formats: [], onExport } as const).not.toExtend<PrintExportBarProps>();
    expectTypeOf({ formats: ["xlsx"], onExport } as const).not.toExtend<PrintExportBarProps>();
  });

  it("has no serious or critical axe violation, idle or running", async () => {
    const host = await mount(
      <div>
        <PrintExportBar formats={["csv", "pdf"]} onExport={fn()} />
        <PrintExportBar formats={["csv"]} onExport={fn()} loading />
      </div>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("printexportbar.css contract (E29-D04 §2.8.9)", () => {
  const css = loadCss("printexportbar.css");
  itIsTokenOnlyAndStatic(css);

  it("spaces the buttons as the toolbar does (E29-D02:493) and wraps rather than clip one", () => {
    const bar = find(css.normal, ".cv-print-export-bar", "gap");
    expect(bar).toContain("gap: var(--space-stack-sm)");
    expect(bar).toContain("flex-wrap: wrap");
  });

  it("running keeps the label at full strength and leads it with CMP-014's arc, in flow", () => {
    const busy = '.cv-print-export-bar > .cv-button[aria-busy="true"]:not([data-side])';
    expect(
      find(css.normal, `${busy} > :is(.cv-button__label, .cv-button__icon)`, "opacity"),
    ).toContain("opacity: 1");
    const arc = find(css.normal, `${busy} > .cv-spinner`, "order");
    expect(arc).toContain("order: -1");
    expect(arc).toContain("position: static");
  });
});

describe("PrintExportBar stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelectorAll('[data-cmp="CMP-099"]').length).toBeGreaterThan(0);
  });
});
