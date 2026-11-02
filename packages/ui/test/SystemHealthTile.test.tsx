// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, type JSX, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  SYSTEM_HEALTH_TILE_COPY as COPY,
  SystemHealthTile,
  type LinkRouteProps,
  type SystemHealthTileProps,
} from "../src/components/index.js";
import * as stories from "../src/components/SystemHealthTile.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

/** The E42-D03 worked example's clock: 14:02:11 and 14:01:40 UTC on 2026-10-22. */
const AS_OF = Date.UTC(2026, 9, 22, 14, 2, 11);
const GOOD = Date.UTC(2026, 9, 22, 14, 1, 40);
const noop = (): void => undefined;
/** Ages are never live; the shell announces a transition once (E42-D03 §13). */
const LIVE = "[aria-live], [role='status'], [role='alert'], [role='log']";
const BASE: SystemHealthTileProps = { label: "Users", href: "/u", state: "ready", tone: "ok" };
/** Every optional line at once (E42-D05 HL-3). */
const FULL: Partial<SystemHealthTileProps> = {
  env: "live",
  tone: "warning",
  stateWord: "Degraded",
  detail: "reconnected 3× in the last hour",
  value: 210,
  valueLabel: "probe",
  unit: "ms",
  unitSpoken: "milliseconds",
  asOf: AS_OF,
  lastGoodAt: GOOD,
  stopsWorking: "updates may lag.",
  stillSafe: true,
  hint: "Check the link.",
  runbookHref: "#runbook",
  onRetry: noop,
};

const show = (
  props: Partial<SystemHealthTileProps> = {},
  lines?: ReactNode,
): Promise<HTMLElement> =>
  mount(
    <SystemHealthTile {...BASE} {...props}>
      {lines}
    </SystemHealthTile>,
  );
const part = (host: HTMLElement, name: string): HTMLElement | null =>
  host.querySelector<HTMLElement>(`.cv-health-tile__${name}`);
/** What a reader hears (`aria-hidden` dropped) or sees (visually hidden dropped), spaces collapsed. */
const text = (el: Element | null, drop: string): string => {
  const copy = el?.cloneNode(true) as Element | undefined;
  copy?.querySelectorAll(drop).forEach((node) => node.remove());
  return (copy?.textContent ?? "").replace(/\s+/g, " ").trim();
};
const heard = (el: Element | null): string => text(el, '[aria-hidden="true"]');
const seen = (el: Element | null): string => text(el, ".cv-visually-hidden");

describe("SystemHealthTile (CMP-178)", () => {
  it("is a region named by its heading link; the env word joins the region's name, not the link's", async () => {
    const host = await show();
    const heading = within(host).getByRole("heading", { level: 3, name: "Users" });
    expect(within(heading).getByRole("link", { name: "Users" })).toHaveAttribute("href", "/u");
    expect(within(host).getByRole("region", { name: "Users" })).toContainElement(heading);
    expect(host.querySelectorAll('[data-cmp="CMP-178"]')).toHaveLength(1);
    expect(COPY.env).toEqual({ live: "LIVE", demo: "DEMO", testnet: "TESTNET" });
    for (const env of ["live", "demo", "testnet"] as const) {
      const name = `Users ${COPY.env[env]}`;
      const tile = within(await show({ env, headingLevel: 2 })).getByRole("region", { name });
      expect(within(tile).getByRole("heading", { level: 2 })).toBeVisible();
      expect(within(tile).getByRole("link")).toHaveAccessibleName("Users");
    }
  });

  it("badges the environment with a class modifier, never a data attribute", async () => {
    // The top bar's badge owns the attribute: its guard rejects any shipped selector that names it.
    for (const env of ["live", "demo", "testnet"] as const) {
      const host = await show({ env });
      const badge = part(host, "env");
      expect(badge?.textContent).toBe(COPY.env[env]);
      expect(badge?.className).toBe(`cv-health-tile__env cv-health-tile__env--${env}`);
      expect(badge?.getAttributeNames()).toEqual(["class"]);
      expect(host.querySelector("[data-env], [data-environment]")).toBeNull();
      // The words and names are the ones the attribute read: the badge is no role, no label.
      expect(within(host).getByRole("region")).toHaveAccessibleName(`Users ${COPY.env[env]}`);
    }
    expect(part(await show(), "env")).toBeNull();
  });

  it("routes the heading through the app's router link when the host passes one", async () => {
    const Route = ({ to, children, ...rest }: LinkRouteProps): JSX.Element => (
      <a {...rest} href={to} data-to={to}>
        {children}
      </a>
    );
    const host = await show({ linkAs: Route });
    expect(within(host).getByRole("link", { name: "Users" })).toHaveAttribute("data-to", "/u");
  });

  it.each([
    ["ok", "check", "ok"],
    ["warning", "warning", "warning"],
    ["danger", "danger", "down"],
    ["stale", "pending", "stale"],
    ["neutral", "ring", "Not built yet"],
  ] as const)("tone %s: one hidden glyph, %s, and the word %s", async (tone, shape, word) => {
    const host = await show({ tone });
    const glyph = part(host, "glyph");
    expect(glyph).toHaveAttribute("data-tone", tone);
    expect(glyph).toHaveAttribute("aria-hidden", "true");
    expect(glyph?.querySelector("svg")?.dataset["icon"] ?? (part(host, "ring") && "ring")).toBe(
      shape,
    );
    expect(seen(part(host, "state"))).toBe(word);
  });

  it.each([
    ["error", "Error"],
    ["unavailable", "Unavailable"],
  ] as const)(
    "%s: the down octagon and '%s — {detail}', whatever the tone",
    async (state, word) => {
      const host = await show({ state, detail: "not built yet" });
      expect(part(host, "glyph")).toHaveAttribute("data-tone", "danger");
      expect(part(host, "glyph")?.querySelector("svg")).toHaveAttribute("data-icon", "danger");
      expect(seen(part(host, "state"))).toBe(`${word} — not built yet`);
    },
  );

  it("renders the host's word verbatim and prefixes a warning, only a warning, with 'Attention:'", async () => {
    const state = part(await show(FULL), "state");
    expect(heard(state)).toBe("Attention: Degraded — reconnected 3× in the last hour");
    expect(seen(state)).toBe("Degraded — reconnected 3× in the last hour");
    for (const tone of ["ok", "danger", "stale", "neutral"] as const) {
      expect(heard(part(await show({ tone }), "state"))).not.toContain(COPY.attention);
    }
  });

  it("reads the unit in words and stamps UTC times; stale reads 'stale since'; never a bad time", async () => {
    const host = await show({ ...FULL, valueAsOf: GOOD });
    expect(seen(part(host, "value"))).toBe("probe 210 ms · as of 14:01:40");
    expect(heard(part(host, "value"))).toBe("probe 210 milliseconds · as of 14:01:40");
    const times = [...host.querySelectorAll(".cv-health-tile__meta")].map((p) => p.textContent);
    expect(times).toEqual(["last good 14:01:40", "as of 14:02:11"]);
    const stale = await show({
      tone: "stale",
      staleSince: AS_OF,
      asOf: Number.NaN,
      lastGoodAt: Infinity,
    });
    expect(seen(part(stale, "state"))).toBe("stale since 14:02:11");
    expect(part(stale, "meta")).toBeNull();
  });

  it.each([null, undefined, "", NaN, Infinity])(
    "no number for a value not received: %s",
    async (value) => {
      const line = part(await show({ value, unit: "ms", valueAsOf: GOOD }), "value");
      expect(seen(line)).toBe(`— ${COPY.notReceived}`);
      expect(heard(line)).toBe(COPY.notReceived);
      expect(part(await show(), "value")).toBeNull();
    },
  );

  it("orders the parts: word, value, host lines, last good, stops, still safe, hint, Runbook, as of, Retry", async () => {
    // CR-5287-02: E42-D03 board 09's Warning specimen draws "last good" over what stops working
    // and "as of" last, each on its own line.
    const host = await show(FULL, <p>host line</p>);
    const tile = within(host);
    const runbook = tile.getByRole("link", { name: COPY.runbook });
    expect(runbook).toHaveAttribute("href", "#runbook");
    expect(COPY.stillSafe).toBe("Native stops on the exchange are unaffected.");
    const parts = [
      ...["state", "value"].map((name) => part(host, name)),
      tile.getByText("host line"),
      tile.getByText("last good 14:01:40"),
      ...["updates may lag.", COPY.stillSafe, "Check the link."].map((t) => tile.getByText(t)),
      runbook,
      tile.getByText("as of 14:02:11"),
      tile.getByRole("button", { name: COPY.retry }),
    ];
    parts.slice(1).forEach((el, i) => {
      expect(
        (parts[i]?.compareDocumentPosition(el as Node) ?? 0) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });
  });

  it("Retry calls onRetry; while loading it stays, busy, and keeps a pressed Retry's focus", async () => {
    const onRetry = fn();
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    const render = (state: SystemHealthTileProps["state"]): Promise<void> =>
      act(async () => root.render(<SystemHealthTile {...BASE} state={state} onRetry={onRetry} />));
    await render("error");
    const retry = within(host).getByRole("button", { name: COPY.retry });
    await userEvent.click(retry);
    expect(onRetry).toHaveBeenCalledTimes(1);
    await render("loading");
    expect(document.activeElement).toBe(retry);
    expect(retry).toHaveAttribute("aria-busy", "true");
    await userEvent.click(retry);
    expect(onRetry).toHaveBeenCalledTimes(1);
    await render("error");
    expect(document.activeElement).toBe(retry);
    await act(async () => root.unmount());
  });

  it("gives the heading link the focus a dropped Retry held; no other focus moves", async () => {
    const host = document.body.appendChild(document.createElement("div"));
    const outside = document.body.appendChild(document.createElement("button"));
    const root = createRoot(host);
    const render = (props: Partial<SystemHealthTileProps>): Promise<void> =>
      act(async () => root.render(<SystemHealthTile {...BASE} {...props} />));
    const retry = (): HTMLElement => within(host).getByRole("button", { name: COPY.retry });
    // Focused through the re-read, then the host drops onRetry for the good read: focus never
    // falls to <body>, it lands on the tile's heading link.
    await render({ state: "error", onRetry: noop });
    act(() => retry().focus());
    await render({ state: "loading", onRetry: noop });
    expect(document.activeElement).toBe(retry());
    await render({ state: "ready" });
    expect(within(host).queryByRole("button")).toBeNull();
    expect(document.activeElement).toBe(within(host).getByRole("link", { name: "Users" }));
    // A Retry that did not hold focus goes without moving it: from another control, or from none.
    await render({ state: "error", onRetry: noop });
    act(() => outside.focus());
    await render({ state: "ready" });
    expect(document.activeElement).toBe(outside);
    await render({ state: "error", onRetry: noop });
    act(() => outside.blur());
    await render({ state: "ready" });
    expect(document.activeElement).toBe(document.body);
    await act(async () => root.unmount());
  });

  it("gives the heading link the focus of any line a re-render takes out; a blur on purpose stays", async () => {
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    const render = (lines?: ReactNode, props: Partial<SystemHealthTileProps> = {}): Promise<void> =>
      act(async () =>
        root.render(
          <SystemHealthTile {...BASE} {...props}>
            {lines}
          </SystemHealthTile>,
        ),
      );
    const heading = (): HTMLElement => within(host).getByRole("link", { name: "Users" });
    const row = (id: number): JSX.Element => (
      <a key={id} href={`#entry-${id}`}>
        {`Entry ${id}`}
      </a>
    );
    // A host row a re-read replaced (A-5330-02): focus lands on the heading link, never <body>.
    await render([row(1), row(2)]);
    act(() => within(host).getByRole("link", { name: "Entry 2" }).focus());
    await render([row(3), row(4)]);
    expect(document.activeElement).toBe(heading());
    // A Runbook link a recovery took out, the same way.
    await render(undefined, { tone: "danger", runbookHref: "#runbook" });
    act(() =>
      within(host)
        .getByRole("link", { name: /Runbook/ })
        .focus(),
    );
    await render();
    expect(document.activeElement).toBe(heading());
    // Focus the user put on the page itself stays there when the line it left goes.
    await render([row(5)]);
    const entry = within(host).getByRole("link", { name: "Entry 5" });
    act(() => entry.focus());
    await act(async () => entry.blur());
    await render([row(6)]);
    expect(document.activeElement).toBe(document.body);
    await act(async () => root.unmount());
  });

  it("loading: the skeleton, hidden words and aria-busy; no word, value or host lines", async () => {
    const host = await show({ state: "loading", value: 210, detail: "x" }, <p>host line</p>);
    expect(host.querySelector('[data-cmp="CMP-178"]')).toHaveAttribute("aria-busy", "true");
    expect(host.querySelector('[data-cmp="CMP-015"]')).toHaveAttribute("aria-hidden", "true");
    // Hidden in normal media; forced colours, where CMP-015's fills drop, show them (the css test).
    expect(within(host).getByText(COPY.loading)).toHaveClass(
      "cv-visually-hidden",
      "cv-health-tile__loading",
    );
    expect(
      part(host, "state") ?? part(host, "value") ?? within(host).queryByText("host line"),
    ).toBeNull();
    expect((await show()).querySelector("[aria-busy]")).toBeNull();
  });

  it.each(["loading", "ready", "error", "unavailable"] as const)(
    "%s: no live region",
    async (state) => {
      expect((await show({ ...FULL, state })).querySelector(LIVE)).toBeNull();
    },
  );

  it("passes axe (serious and critical) as a full tile and as a loading one", async () => {
    expect(await seriousViolations(await show(FULL))).toEqual([]);
    expect(await seriousViolations(await show({ state: "loading", onRetry: noop }))).toEqual([]);
  });
});

describe("SystemHealthTile stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders a region", async (_name, Story) => {
    expect(within(await mount(<Story />)).getAllByRole("region").length).toBeGreaterThan(0);
  });
});
