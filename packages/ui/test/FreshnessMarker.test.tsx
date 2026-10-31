// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  DATA_CONFIDENCE_PRECEDENCE,
  FreshnessMarker,
  formatStaleAge,
  freshnessClassName,
  freshnessOf,
  staleAgeName,
  type DataConfidenceState,
} from "../src/index.js";
import { seriousViolations } from "./axe.js";
import * as stories from "../src/components/FreshnessMarker.stories.js";
import { mount } from "./theme/mount.js";

describe("formatStaleAge (E08-D07 D34)", () => {
  it("seconds under a minute: Stale 7s", () => {
    expect([formatStaleAge(7000), formatStaleAge(59_999)]).toEqual(["Stale 7s", "Stale 59s"]);
  });

  it("whole minutes under an hour: Stale 2m", () => {
    expect([formatStaleAge(60_000), formatStaleAge(125_000)]).toEqual(["Stale 1m", "Stale 2m"]);
  });

  it("whole hours from an hour: Stale 1h", () => {
    expect([formatStaleAge(3_600_000), formatStaleAge(7_300_000)]).toEqual([
      "Stale 1h",
      "Stale 2h",
    ]);
  });
});

describe("staleAgeName (the chip's name, the `15` L2214 form)", () => {
  it("Stale, 7 seconds; one second is singular", () => {
    expect([staleAgeName(7000), staleAgeName(1000)]).toEqual([
      "Stale, 7 seconds",
      "Stale, 1 second",
    ]);
  });

  it("minutes and hours", () => {
    expect([staleAgeName(60_000), staleAgeName(150_000), staleAgeName(3_600_000)]).toEqual([
      "Stale, 1 minute",
      "Stale, 2 minutes",
      "Stale, 1 hour",
    ]);
  });
});

describe("freshnessOf (E08-D01 §2 precedence: one state, never stacked)", () => {
  it("the order is delisted, disconnected, reconnecting, resyncing, gapped, backfilling, stale, live", () => {
    expect(DATA_CONFIDENCE_PRECEDENCE).toEqual([
      "delisted",
      "disconnected",
      "reconnecting",
      "resyncing",
      "gapped",
      "backfilling",
      "stale",
      "live",
    ]);
  });

  it("the highest state wins", () => {
    expect(freshnessOf(["stale", "disconnected"])).toBe("disconnected");
    expect(freshnessOf(["live", "stale", "delisted"])).toBe("delisted");
  });

  it("nothing degraded is live", () => {
    expect(freshnessOf([])).toBe("live");
    expect(freshnessOf(["live"])).toBe("live");
  });
});

describe("freshnessClassName (the compact presentation: the cell only swaps a class)", () => {
  it("live adds no class: the absence of a marker is the live state", () => {
    expect(freshnessClassName("live")).toBeUndefined();
  });

  it.each(DATA_CONFIDENCE_PRECEDENCE.filter((s) => s !== "live"))(
    "%s is one className, never a node",
    async (state: DataConfidenceState) => {
      const host = await mount(
        <table>
          <tbody>
            <tr>
              <td className={freshnessClassName(state)}>64,012.50</td>
            </tr>
          </tbody>
        </table>,
      );
      const cell = host.querySelector("td") as HTMLElement;
      expect(cell).toHaveClass(`cv-freshness--${state}`);
      expect(cell.childNodes).toHaveLength(1);
    },
  );
});

describe("FreshnessMarker (CMP-239), compact", () => {
  it("draws the age once, Stale 7s, and reads it Stale, 7 seconds", async () => {
    const host = await mount(
      <FreshnessMarker presentation="compact" state="stale" lastUpdatedAgeMs={7000} />,
    );
    const chip = host.querySelector('[data-cmp="CMP-239"]') as HTMLElement;
    expect(chip.querySelector('[aria-hidden="true"]')).toHaveTextContent("Stale 7s");
    expect(within(chip).getByText("Stale, 7 seconds")).toHaveClass("cv-visually-hidden");
  });

  it("is the description of the cells that point at it", async () => {
    const host = await mount(
      <div>
        <FreshnessMarker
          id="sol-age"
          presentation="compact"
          state="stale"
          lastUpdatedAgeMs={7000}
        />
        <span role="gridcell" tabIndex={-1} aria-describedby="sol-age">
          142.37
        </span>
      </div>,
    );
    expect(within(host).getByRole("gridcell")).toHaveAccessibleDescription("Stale, 7 seconds");
  });

  it("is the T1 chip until escalated, then the strong one (E08-D07 D1)", async () => {
    const host = await mount(
      <>
        <FreshnessMarker presentation="compact" state="stale" lastUpdatedAgeMs={7000} />
        <FreshnessMarker presentation="compact" state="stale" lastUpdatedAgeMs={15_000} escalated />
      </>,
    );
    const chips = host.querySelectorAll('[data-cmp="CMP-239"]');
    expect([...chips].map((c) => c.getAttribute("data-level"))).toEqual(["subtle", "strong"]);
  });

  it("a label overrides the words: Stale (server), drawn and read the same", async () => {
    const host = await mount(
      <FreshnessMarker presentation="compact" state="stale" label="Stale (server)" />,
    );
    expect(host).toHaveTextContent("Stale (server)");
    expect(host.querySelector(".cv-visually-hidden")).toBeNull();
  });

  it("owns no live region: an age change is never announced", async () => {
    const host = await mount(
      <FreshnessMarker presentation="compact" state="stale" lastUpdatedAgeMs={7000} />,
    );
    expect(host.querySelector("[role=status], [role=alert], [aria-live]")).toBeNull();
  });

  it("axe: no serious or critical violation", async () => {
    const host = await mount(
      <FreshnessMarker presentation="compact" state="stale" lastUpdatedAgeMs={7000} escalated />,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

// Each story's play in jsdom (the storybook project runs them in Chromium, with axe).
describe("FreshnessMarker stories", () => {
  it("runs each story's play function", { timeout: 30_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
      canvasElement.remove();
    }
  });
});
