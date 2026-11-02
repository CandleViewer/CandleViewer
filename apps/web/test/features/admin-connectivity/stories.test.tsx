import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { COPY } from "../../../src/features/admin-connectivity/copy";
import {
  STORIES,
  STORY_THEMES,
  type StoryDef,
} from "../../../src/features/admin-connectivity/stories";
import * as fixtures from "../../../src/features/admin-connectivity/fixtures";

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
});

const FEATURE = resolve(import.meta.dirname, "../../../src/features/admin-connectivity");

// The hand-off §D lists: the story names each component must carry (E08-D09-handoff §D).
const REQUIRED: Readonly<Record<StoryDef["cmp"], readonly string[]>> = {
  "CMP-178": ["RateHeld", "RateBanned", "ClockHalted", "NotMeasured"],
  "CMP-023": ["MeterStepped", "MeterNotConnected"],
  "CMP-049": ["BudgetGrid", "BudgetGridPerMinute", "SimulatorResult", "HistoryTable"],
  "CMP-044": ["ReconnectMarketData", "ChangeBudget", "ChangeBudgetRefused"],
  "CMP-079": ["HoldReason", "ConnectionBudgetWait", "ViewAs"],
  "CMP-024": ["UsageHistory", "UsageHistoryEmpty"],
  "CMP-093": ["MarkerPendingRegistration"],
};

/** Everything a person or a screen reader could be handed: the DOM, attributes and portals included. */
const FORBIDDEN: ReadonlyArray<readonly [string, RegExp]> = [
  ["a UUID", /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i],
  [
    "a host or URL",
    /https?:\/\/|\b[a-z0-9-]+\.(com|net|org|io|app|dev|local)\b|\bbybit\b|\bbytick\b/i,
  ],
  ["an IP address", /\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/],
  ["a key or secret", /api[-_ ]?key|secret|token|passw|signature|bearer/i],
  ["a trace or request id", /trace[-_ ]?id|request[-_ ]?id|correlation|x-request/i],
  ["a long opaque token", /\b[A-Za-z0-9+/_-]{32,}\b/],
];

// The icons' SVG namespace is a W3C identifier, not a host of ours.
const NAMESPACE = /\sxmlns="http:\/\/www\.w3\.org\/2000\/svg"/g;

const scan = (where: string, raw: string): void => {
  const text = raw.replace(NAMESPACE, "");
  for (const [what, re] of FORBIDDEN) expect(text, `${where}: ${what}`).not.toMatch(re);
};

describe("the §D story lists", () => {
  it("carry every named story, once", () => {
    for (const [cmp, names] of Object.entries(REQUIRED))
      for (const name of names)
        expect(
          STORIES.filter((s) => s.cmp === cmp && s.name === name),
          `${cmp} ${name}`,
        ).toHaveLength(1);
  });

  describe.each(STORY_THEMES)("in %s", (theme) => {
    it.each(STORIES.map((s) => [s.cmp, s.name, s] as const))(
      "%s %s renders and prints no key, host, UUID or id",
      async (_c, name, story) => {
        document.documentElement.setAttribute("data-theme", theme);
        render(story.render());
        if (name.startsWith("Reconnect") || name.startsWith("ChangeBudget"))
          await screen.findByRole("alertdialog");
        scan(`${name} (${theme})`, document.body.innerHTML);
        expect(document.body.textContent ?? "").not.toBe("");
      },
    );
  });

  it("MeterNotConnected draws no meter and MeterStepped names its numbers", () => {
    const find = (n: string): StoryDef => {
      const s = STORIES.find((x) => x.name === n);
      if (s === undefined) throw new Error(n);
      return s;
    };
    const not = render(find("MeterNotConnected").render());
    expect(screen.queryByRole("meter")).toBeNull();
    expect(not.container).toHaveTextContent("Not connected yet");
    cleanup();
    render(find("MeterStepped").render());
    expect(screen.getByRole("meter")).toHaveAttribute(
      "aria-valuetext",
      expect.stringMatching(/^\d+ requests per minute of/),
    );
  });

  it("MarkerPendingRegistration prints the label and never a code", () => {
    const s = STORIES.find((x) => x.name === "MarkerPendingRegistration");
    render((s as StoryDef).render());
    expect(document.body).toHaveTextContent(COPY["W-55"]);
    expect(document.body.textContent).not.toMatch(/connectivity\.\w+/);
  });
});

/** Source files may name identifiers and a comment's words: only ids, hosts, keys and long tokens are scanned. */
// In source, deck words ("signatures") and SCREAMING_CASE names are not secrets: the key pattern is an assignment of
// key material and the long token must mix lower case and a digit.
const SOURCE_PATTERNS = FORBIDDEN.filter(([w]) => w !== "a trace or request id")
  .map(([w, re]): readonly [string, RegExp] =>
    w === "a key or secret"
      ? [
          w,
          /(api[-_ ]?key|secret|token|passw\w*|signature|bearer)\w*["']?\s*[:=]\s*["'`][^"'`\s]{8,}/i,
        ]
      : w === "a long opaque token"
        ? [w, /\b(?=[A-Za-z0-9+/_-]*\d)(?=[A-Za-z0-9+/_-]*[a-z])[A-Za-z0-9+/_-]{32,}\b/]
        : [w, re],
  )
  .concat([["a key-shaped literal", /\b(sk|pk|rk|ak)_(live|test)_[A-Za-z0-9]{8,}/]]);

/** The name of the first pattern a probe trips, or null. */
const firstHit = (raw: string, patterns: typeof FORBIDDEN): string | null =>
  patterns.find(([, re]) => re.test(raw.replace(NAMESPACE, "")))?.[0] ?? null;

describe("the text scan reaches fixtures and every source (C-13.5, SR-026)", () => {
  it("finds no UUID, host, key or trace id in a fixture", () => {
    scan("fixtures", JSON.stringify(fixtures));
  });

  it("scans every ts/tsx file of the feature for ids, hosts, key material and long tokens", () => {
    const files = readdirSync(FEATURE).filter((f) => /\.tsx?$/.test(f));
    expect(files.length).toBeGreaterThanOrEqual(15);
    for (const file of files) {
      const hit = firstHit(readFileSync(resolve(FEATURE, file), "utf8"), SOURCE_PATTERNS);
      expect(hit, `${file} trips ${hit}`).toBeNull();
    }
  });

  it("the scan names the specific pattern each probe trips", () => {
    // Probes are assembled at run time so this file holds no key-shaped literal for the secret scanner.
    const probes: ReadonlyArray<readonly [string, string, typeof FORBIDDEN]> = [
      ["0b9d7c1e-0000-4000-8000-000000000001", "a UUID", FORBIDDEN],
      ["api.bybit.com", "a host or URL", FORBIDDEN],
      ["10.0.0.12", "an IP address", FORBIDDEN],
      ["trace_id=abc", "a trace or request id", FORBIDDEN],
      ["api_key", "a key or secret", FORBIDDEN],
      [["apiKey", ' = "', "abcdefgh1234", '"'].join(""), "a key or secret", SOURCE_PATTERNS],
      ["AbCdEfGhIjKlMnOpQrStUvWxYz0123456789", "a long opaque token", FORBIDDEN],
      [["sk", "live", "abcdefgh12345678"].join("_"), "a key-shaped literal", SOURCE_PATTERNS],
      ["0b9d7c1e-0000-4000-8000-000000000001", "a UUID", SOURCE_PATTERNS],
      ["https://example.com", "a host or URL", SOURCE_PATTERNS],
    ];
    for (const [bad, name, set] of probes) expect(firstHit(bad, set), bad).toBe(name);
  });

  it("a planted value in a rendered story is caught by the DOM scan", () => {
    const planted = STORIES.find((x) => x.name === "BudgetGrid") as StoryDef;
    render(planted.render());
    const planting = document.createElement("span");
    planting.setAttribute("data-x", "0b9d7c1e-0000-4000-8000-000000000001");
    document.body.appendChild(planting);
    expect(() => scan("planted", document.body.innerHTML)).toThrow(/a UUID/);
  });
});
