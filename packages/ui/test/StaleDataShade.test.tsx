// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act } from "react";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  StaleDataShade,
  staleAsOf,
  staleDataRowClassName,
  type StaleDataShadeProps,
} from "../src/index.js";
import * as stories from "../src/components/StaleDataShade.stories.js";
import { seriousViolations } from "./axe.js";
import { cascadedProperty } from "./cascade.js";
import { shippedComponentsCss } from "./componentsCss.js";
import { find, loadCss } from "./css-contract.js";
import { mount } from "./theme/mount.js";

const AT = Date.UTC(2026, 10, 3, 14, 2, 11);
const css = loadCss("staledatashade.css");

const shade = (host: HTMLElement): HTMLElement => {
  const el = host.querySelector<HTMLElement>('[data-cmp="CMP-078"]');
  if (el === null) throw new Error("no shade rendered");
  return el;
};

function Host(props: Omit<StaleDataShadeProps, "children">): React.JSX.Element {
  return (
    <StaleDataShade {...props}>
      <section aria-label="Orders" aria-describedby={props.id}>
        <button type="button">Filter</button>
      </section>
    </StaleDataShade>
  );
}

describe("StaleDataShade (CMP-078)", () => {
  it("fresh draws nothing: no dim, no words, no state class", async () => {
    const host = await mount(<Host id="w" state="fresh" />);
    expect(shade(host).className).toBe("cv-stale-shade");
    expect(host.querySelector(".cv-stale-shade__dim")).toBeNull();
    expect(host.querySelector("#w")).toBeNull();
  });

  it("stale: the dim is aria-hidden and the panel's description reads the state and its age", async () => {
    const host = await mount(<Host id="w" state="stale" ageMs={7400} />);
    expect(host.querySelector(".cv-stale-shade__dim")).toHaveAttribute("aria-hidden", "true");
    const region = within(host).getByRole("region", { name: "Orders" });
    expect(region).toHaveAccessibleDescription(/Stale, 7 seconds.*Last update 7 s ago/);
  });

  it("the escalated strip leads with a decorative warning glyph (E17-D02 §7)", async () => {
    const host = await mount(<Host id="w" state="escalated" ageMs={15_000} strip="Stale 15 s." />);
    const strip = host.querySelector(".cv-stale-shade__strip");
    expect(strip?.querySelector("svg")).not.toBeNull();
    expect(strip?.querySelector('[aria-hidden="true"]')).not.toBeNull();
    expect(strip).toHaveTextContent("Stale 15 s.");
  });

  it("owns no live region and never announces (the host says one sentence per episode)", async () => {
    for (const state of ["fresh", "stale", "escalated", "stale-server", "disconnected"] as const) {
      const host = await mount(<Host id={`w-${state}`} state={state} ageMs={15_000} strip="Stale 15 s." />);
      expect(host.querySelector("[role=status], [role=alert], [aria-live]"), state).toBeNull();
    }
  });

  it("with no age given none is drawn or read: no chip, no 'Stale 0s', no 'last data 00:00' (C-2.12)", async () => {
    const account = await mount(<Host id="a" state="stale" lastGoodTs={AT} />);
    expect(account.querySelector(".cv-freshness-chip")).toBeNull();
    expect(account).not.toHaveTextContent(/Stale\s*0|0 s ago|0 seconds/);
    expect(account).toHaveTextContent("Not up to date · as of 14:02:11 UTC");
    const plain = await mount(<Host id="b" state="escalated" strip="Stale." />);
    expect(plain.querySelector(".cv-freshness-chip")).toBeNull();
    expect(plain.querySelector("#b")).toHaveTextContent(/^Not up to date$/);
    const gone = await mount(<Host id="c" state="disconnected" />);
    expect(gone.querySelector("#c")).toHaveTextContent(/^Disconnected$/);
    const real = await mount(<Host id="d" state="stale" ageMs={0} />);
    expect(real.querySelector(".cv-freshness-chip")).not.toBeNull();
  });

  it.each([
    [
      { state: "escalated", ageMs: 15_000, strip: "Stale 15 s — new orders blocked on BTCUSDT" },
      "Stale 15 s — new orders blocked on BTCUSDT",
    ],
    [{ state: "stale-server", sinceTs: AT }, "Stale (server) — since 14:02:11"],
    [{ state: "stale-server" }, "Stale (server)"],
    [{ state: "disconnected", ageMs: 72_000 }, "Disconnected — last data 01:12"],
    [{ state: "stale", lastGoodTs: AT }, "Not up to date · as of 14:02:11 UTC"],
    [{ state: "disconnected", label: "Resyncing book…" }, "Resyncing book…"],
  ] as const)("%o reads %s", async (props, text) => {
    const host = await mount(<Host id="w" {...props} />);
    expect(host).toHaveTextContent(text);
  });

  it("a state change keeps the panel mounted, so focus inside it stays (never inert)", async () => {
    const host = document.body.appendChild(document.createElement("div"));
    const { createRoot } = await import("react-dom/client");
    const root = createRoot(host);
    await act(async () => root.render(<Host id="w" state="fresh" />));
    const button = within(host).getByRole("button", { name: "Filter" });
    button.focus();
    await act(async () => root.render(<Host id="w" state="disconnected" ageMs={12_000} />));
    expect(within(host).getByRole("button", { name: "Filter" })).toBe(button);
    expect(button).toHaveFocus();
    expect(host.querySelector("[inert]")).toBeNull();
    await act(async () => root.unmount());
  });

  it("the grid-row variant is a class swap; fresh adds none", () => {
    expect(staleDataRowClassName("fresh")).toBeUndefined();
    expect(staleDataRowClassName("stale")).toBe("cv-stale-row cv-stale-row--stale");
    expect(staleAsOf(AT)).toBe("as of 14:02:11 UTC");
    expect(staleAsOf(Number.NaN)).toBe("as of 00:00:00 UTC");
  });

  it("axe: no serious or critical violation in any state", { timeout: 30_000 }, async () => {
    for (const state of ["fresh", "stale", "escalated", "stale-server", "disconnected"] as const) {
      const host = await mount(
        <Host id={`w-${state}`} state={state} ageMs={7000} strip="Stale." />,
      );
      expect(await seriousViolations(host), state).toEqual([]);
    }
  });
});

describe("staledatashade.css contract", () => {
  it("binds tokens only: no raw colour, and raw px only for forced-colours edges", () => {
    expect(css.normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(css.normal.replace(/\* 1px/g, "")).not.toMatch(/\d+px/);
    expect(css.all).not.toMatch(/transition|animation/);
  });

  it("the dim composites stale.surface at 0.15 (the PROPOSED color.overlay.stale) and takes no pointer", () => {
    const dim = find(css.normal, ".cv-stale-shade__dim", "background");
    expect(dim).toContain("var(--color-data-confidence-stale-surface)");
    expect(dim).toContain("opacity: var(--cv-stale-shade-dim)");
    expect(dim).toContain("pointer-events: none");
    expect(find(css.normal, ".cv-stale-shade", "--cv-stale-shade-dim")).toMatch(/0\.15/);
  });

  it("the scrim is surface.overlay at opacity.scrim; forced colours drop the dim, the words keep an edge", () => {
    const scrim = find(
      css.normal,
      ".cv-stale-shade--disconnected .cv-stale-shade__dim",
      "background",
    );
    expect(scrim).toContain("var(--color-surface-overlay)");
    expect(scrim).toContain("var(--opacity-scrim)");
    expect(find(css.normal, ".cv-stale-shade--disconnected .cv-stale-shade__dim", "pointer-events")).toContain(
      "auto",
    );
    expect(find(css.forced, ".cv-stale-shade__dim", "background")).toContain("transparent");
    expect(find(css.forced, ".cv-stale-shade__text", "border")).toContain("CanvasText");
  });
});

// freshness-css precedent: copy-css concatenates by file name, so table.css (zebra, hover, text.primary cells) sorts
// after staledatashade.css and out-ranks equal specificity; the variant must still win on a CMP-049 row.
describe("staledatashade.css in the shipped components.css", () => {
  it("a stale row keeps its stale tint and demoted text on an even (zebra) row and its cells", async () => {
    const host = await mount(
      <table>
        <tbody>
          <tr className="cv-table__row">
            <td className="cv-table__cell">odd</td>
          </tr>
          <tr className={`cv-table__row ${staleDataRowClassName("stale") ?? ""}`}>
            <td className="cv-table__cell">even</td>
          </tr>
        </tbody>
      </table>,
    );
    const row = host.querySelectorAll("tr")[1] as HTMLElement;
    const cell = row.querySelector("td") as HTMLElement;
    const sheet = shippedComponentsCss();
    expect(cascadedProperty(sheet, row, "background")).toBe("var(--color-data-confidence-stale-surface)");
    expect(cascadedProperty(sheet, cell, "color")).toBe("var(--color-data-confidence-stale-text)");
  });
});

describe("StaleDataShade stories", () => {
  it("runs each story's play function", { timeout: 30_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
      canvasElement.remove();
    }
  });

  it("covers every catalogued state plus hover, focus and long text", () => {
    expect(Object.keys(composeStories(stories))).toEqual(
      expect.arrayContaining([
        "Fresh",
        "Stale",
        "Escalated",
        "StaleServer",
        "Disconnected",
        "ReducedMotion",
        "Hover",
        "FocusVisible",
        "LongText",
      ]),
    );
  });
});
