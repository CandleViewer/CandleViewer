// @vitest-environment jsdom
import { act, Profiler, StrictMode, useEffect, useState, type JSX } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { expect, fireEvent, fn, within } from "storybook/test";
import { MaskedValue, maskAllValues, type MaskedValueProps } from "../src/components/index.js";
import {
  clampAutoHide,
  MASKED_VALUE_AUTO_HIDE_MAX_MS,
  MASKED_VALUE_AUTO_HIDE_MIN_MS,
  MASKED_VALUE_AUTO_HIDE_MS,
} from "../src/components/MaskedValue.js";
import { mount } from "./theme/mount.js";

/** A stand-in that looks like a secret: while masked it must appear nowhere in the document. */
const VALUE = "sk-demo-4f9c2e7a1b";
const MASK = "•".repeat(8);
const LABEL = "API secret";
const WARNING = "API secret will hide in 2 seconds";
const writeText = vi.fn<(text: string) => Promise<void>>();
const escaped = new RegExp(VALUE.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));

beforeEach(() => {
  vi.useFakeTimers();
  writeText.mockReset();
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});

afterEach(() => {
  vi.useRealTimers();
  Reflect.deleteProperty(navigator, "clipboard");
  Reflect.deleteProperty(document, "visibilityState");
});

const render = (props: Partial<MaskedValueProps> = {}): Promise<HTMLElement> =>
  mount(<MaskedValue value={VALUE} label={LABEL} {...props} />);
const press = async (el: HTMLElement): Promise<void> => {
  await act(async () => {
    fireEvent.click(el);
  });
};
const advance = async (ms: number): Promise<void> => {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
};
const fire = async (target: EventTarget, type: string): Promise<void> => {
  await act(async () => {
    target.dispatchEvent(new Event(type));
  });
};
const toggle = (host: HTMLElement): HTMLElement =>
  within(host).getByRole("button", { name: /^(Show|Hide) API secret$/ });
const copyButton = (host: HTMLElement): HTMLElement =>
  within(host).getByRole("button", { name: "Copy API secret" });
const root = (host: HTMLElement): HTMLElement =>
  host.querySelector<HTMLElement>(".cv-masked-value") ?? host;
const stateOf = (host: HTMLElement): string => root(host).dataset["state"] ?? "";

/**
 * S4's scan: the value is in no text node, no attribute (title, data-*, aria-* included), no accessible
 * name and no accessible description anywhere in the document.
 */
const expectValueAbsent = (): void => {
  expect(document.documentElement.outerHTML).not.toContain(VALUE);
  expect(document.title).not.toContain(VALUE);
  expect(location.href).not.toContain(VALUE);
  for (const store of [localStorage, sessionStorage]) {
    for (let i = 0; i < store.length; i += 1) {
      const key = store.key(i) ?? "";
      expect(key).not.toContain(VALUE);
      expect(store.getItem(key) ?? "").not.toContain(VALUE);
    }
  }
  for (const el of document.querySelectorAll("*")) {
    for (const attr of el.attributes) expect(attr.value).not.toContain(VALUE);
    expect(el.textContent ?? "").not.toContain(VALUE);
    expect(el).not.toHaveAccessibleName(escaped);
    expect(el).not.toHaveAccessibleDescription(escaped);
  }
};

/** The masked look: the 8-dot mask only, hidden from AT, the hidden "{label}, hidden" and a "Show" toggle. */
const expectMasked = (host: HTMLElement): void => {
  expect(stateOf(host)).toBe("masked");
  const mask = host.querySelector(".cv-masked-value__mask");
  expect(mask).toHaveTextContent(MASK);
  expect(mask).toHaveAttribute("aria-hidden", "true");
  expect(within(host).getByText(`${LABEL}, hidden`)).toBeTruthy();
  expect(toggle(host)).toHaveAccessibleName("Show API secret");
  expect(host.querySelector(".cv-masked-value__countdown")).toBeNull();
  expectValueAbsent();
};

/** A spy on every console method, so a test can prove nothing at all was logged. */
const spyOnConsole = (): ReturnType<typeof vi.spyOn>[] =>
  Object.keys(console)
    .filter((key) => typeof (console as unknown as Record<string, unknown>)[key] === "function")
    .map((key) => vi.spyOn(console, key as "log"));

/** Every text node of the document holding the value. */
const textNodesWithValue = (): Text[] => {
  const found: Text[] = [];
  const walker = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode())
    if ((node.nodeValue ?? "").includes(VALUE)) found.push(node as Text);
  return found;
};

/** The re-mask listener types: none may be attached while masked. */
const REMASK_EVENTS = [
  "blur",
  "pagehide",
  "beforeprint",
  "popstate",
  "hashchange",
  "visibilitychange",
];

describe("MaskedValue (CMP-034)", () => {
  it("Scenario: Masked value never leaks by default", async () => {
    // Given a MaskedValue holding a secret
    // When it mounts
    const host = await render({ copyable: true });
    // Then it is a group named by its label, the mask shows, and the value is nowhere
    expect(within(host).getByRole("group", { name: LABEL })).toBe(root(host));
    expect(root(host).dataset["cmp"]).toBe("CMP-034");
    expectMasked(host);
    // And copying is unavailable until it is revealed
    expect(copyButton(host)).toBeDisabled();
  });

  it("S4: the mask is 8 characters whatever the value's length", async () => {
    for (const value of ["a", "12345678", "x".repeat(256)]) {
      const host = await mount(<MaskedValue value={value} label={LABEL} />);
      expect(host.querySelector(".cv-masked-value__mask")?.textContent).toBe(MASK);
    }
  });

  it("S1: `revealed` at mount never reveals", async () => {
    const host = await render({ revealed: true });
    expectMasked(host);
  });

  it("S2: a press reveals the value; the name swaps, no aria-pressed, focus stays", async () => {
    const onToggleReveal = fn();
    const host = await render({ onToggleReveal });
    const button = toggle(host);
    expect(button).not.toHaveAttribute("aria-pressed");
    expect(button).toHaveAttribute(
      "aria-controls",
      host.querySelector(".cv-masked-value__box")?.id,
    );
    button.focus();
    await press(button);
    expect(stateOf(host)).toBe("revealed");
    expect(host.querySelector(".cv-masked-value__value")).toHaveTextContent(VALUE);
    expect(host.querySelector(".cv-masked-value__mask")).toBeNull();
    expect(toggle(host)).toHaveAccessibleName("Hide API secret");
    expect(toggle(host)).toBe(button);
    expect(button).toHaveFocus();
    expect(onToggleReveal).toHaveBeenCalledTimes(1);
    expect(onToggleReveal).toHaveBeenCalledWith(true);
    expect(host.querySelector(".cv-masked-value__countdown")).toHaveTextContent("Hides in 10 s");
  });

  it("S3: Hide re-masks at once and tells the host", async () => {
    const onToggleReveal = fn();
    const host = await render({ onToggleReveal });
    await press(toggle(host));
    await press(toggle(host));
    expectMasked(host);
    expect(onToggleReveal).toHaveBeenLastCalledWith(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("S3: re-masks after 10 s, announced once 2 s before, silent at the moment; focus kept", async () => {
    const onToggleReveal = fn();
    const host = await render({ onToggleReveal });
    const spoken: string[] = [];
    const observer = new MutationObserver(() => {
      const text = host.querySelector('[role="status"]')?.textContent ?? "";
      if (text !== "" && spoken.at(-1) !== text) spoken.push(text);
    });
    observer.observe(host, { childList: true, characterData: true, subtree: true });
    toggle(host).focus();
    await press(toggle(host));
    await advance(MASKED_VALUE_AUTO_HIDE_MS - 2001);
    expect(stateOf(host)).toBe("revealed");
    expect(spoken).toEqual([]);
    await advance(1);
    expect(stateOf(host)).toBe("expiring");
    expect(within(host).getByRole("status")).toHaveTextContent(WARNING);
    await advance(1999);
    expect(stateOf(host)).toBe("expiring");
    await advance(1);
    observer.disconnect();
    expectMasked(host);
    expect(spoken).toEqual([WARNING]);
    expect(toggle(host)).toHaveFocus();
    expect(onToggleReveal).toHaveBeenLastCalledWith(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("S3: a new press after a re-mask restarts the clock and the one warning", async () => {
    const host = await render();
    await press(toggle(host));
    await advance(5000);
    await press(toggle(host));
    await press(toggle(host));
    await advance(MASKED_VALUE_AUTO_HIDE_MS - 1);
    expect(stateOf(host)).toBe("expiring");
    await advance(1);
    expectMasked(host);
  });

  it("G19: autoHideMs is clamped to [3 s, 30 s]; a non-number takes the 10 s default", async () => {
    expect(clampAutoHide(undefined)).toBe(MASKED_VALUE_AUTO_HIDE_MS);
    expect(clampAutoHide(Number.NaN)).toBe(MASKED_VALUE_AUTO_HIDE_MS);
    expect(clampAutoHide(Number.POSITIVE_INFINITY)).toBe(MASKED_VALUE_AUTO_HIDE_MS);
    expect(clampAutoHide(500)).toBe(MASKED_VALUE_AUTO_HIDE_MIN_MS);
    expect(clampAutoHide(60_000)).toBe(MASKED_VALUE_AUTO_HIDE_MAX_MS);
    expect(clampAutoHide(15_000)).toBe(15_000);
    const host = await render({ autoHideMs: 3_600_000 });
    await press(toggle(host));
    await advance(MASKED_VALUE_AUTO_HIDE_MAX_MS - 1);
    expect(stateOf(host)).toBe("expiring");
    await advance(1);
    expectMasked(host);
  });

  it("the shortest auto-hide still speaks its one warning", async () => {
    const host = await render({ autoHideMs: 1 });
    await press(toggle(host));
    await advance(MASKED_VALUE_AUTO_HIDE_MIN_MS - 2000);
    expect(within(host).getByRole("status")).toHaveTextContent(WARNING);
    await advance(2000);
    expectMasked(host);
  });

  it("S1: a hidden tab re-masks; a visible one changes nothing", async () => {
    const host = await render();
    await press(toggle(host));
    await fire(document, "visibilitychange");
    expect(stateOf(host)).toBe("revealed");
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    await fire(document, "visibilitychange");
    expectMasked(host);
  });

  it.each(["blur", "pagehide", "beforeprint", "popstate", "hashchange"])(
    "S1: the window's %s re-masks",
    async (type) => {
      const onToggleReveal = fn();
      const host = await render({ onToggleReveal });
      await press(toggle(host));
      await fire(window, type);
      expectMasked(host);
      expect(onToggleReveal).toHaveBeenLastCalledWith(false);
    },
  );

  it("two re-mask events in one tick tell the host once", async () => {
    const onToggleReveal = fn();
    const host = await render({ onToggleReveal });
    await press(toggle(host));
    await act(async () => {
      window.dispatchEvent(new Event("blur"));
      window.dispatchEvent(new Event("pagehide"));
    });
    expectMasked(host);
    expect(onToggleReveal.mock.calls).toEqual([[true], [false]]);
  });

  it("S1: one revealed value per page; maskAllValues() masks it (route change, idle lock, sign-out)", async () => {
    const a = await mount(<MaskedValue value={VALUE} label={LABEL} />);
    const b = await mount(<MaskedValue value="sk-demo-second" label="API key" />);
    const toggleB = within(b).getByRole("button", { name: "Show API key" });
    await press(toggle(a));
    expect(stateOf(a)).toBe("revealed");
    await press(toggleB);
    expect(stateOf(b)).toBe("revealed");
    expect(stateOf(a)).toBe("masked");
    expect(a.outerHTML).not.toContain(VALUE);
    await act(async () => maskAllValues());
    expect(stateOf(b)).toBe("masked");
    expectValueAbsent();
    expect(vi.getTimerCount()).toBe(0);
    // Nothing revealed: a no-op.
    await act(async () => maskAllValues());
  });

  it("the host's revealed={false} masks at once and a later true does not re-reveal", async () => {
    const onToggleReveal = fn();
    function Host({ revealed }: { revealed: boolean }): JSX.Element {
      return (
        <MaskedValue
          value={VALUE}
          label={LABEL}
          revealed={revealed}
          onToggleReveal={onToggleReveal}
        />
      );
    }
    const host = document.body.appendChild(document.createElement("div"));
    const r = createRoot(host);
    await act(async () => r.render(<Host revealed />));
    await press(toggle(host));
    expect(stateOf(host)).toBe("revealed");
    await act(async () => r.render(<Host revealed={false} />));
    expectMasked(host);
    await act(async () => r.render(<Host revealed />));
    expectMasked(host);
    // The veto itself is the host's: it emits nothing.
    expect(onToggleReveal.mock.calls).toEqual([[true]]);
    // A press under a standing veto reveals nothing and emits nothing (M2).
    await act(async () => r.render(<Host revealed={false} />));
    onToggleReveal.mockClear();
    await press(toggle(host));
    expectMasked(host);
    expect(onToggleReveal).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    await act(async () => r.unmount());
  });

  it("a host that mirrors onToggleReveal without passing it back stays in step", async () => {
    const seen: boolean[] = [];
    function Host(): JSX.Element {
      const [revealed, setRevealed] = useState(false);
      seen.push(revealed);
      // `revealed` is a veto, not a mirror: the host passes `false` only to force the mask.
      return <MaskedValue value={VALUE} label={LABEL} onToggleReveal={setRevealed} />;
    }
    const host = await mount(<Host />);
    await press(toggle(host));
    expect(seen.at(-1)).toBe(true);
    expect(stateOf(host)).toBe("revealed");
    await advance(MASKED_VALUE_AUTO_HIDE_MS);
    expect(seen.at(-1)).toBe(false);
    expectMasked(host);
  });

  it("N1: while revealed the value is in exactly one text node and in no attribute, name or title", async () => {
    const host = await render({ copyable: true });
    await press(toggle(host));
    const nodes = textNodesWithValue();
    expect(nodes).toHaveLength(1);
    expect(nodes[0]?.parentElement?.closest(".cv-masked-value__value")).not.toBeNull();
    expect(document.title).not.toContain(VALUE);
    expect(location.href).not.toContain(VALUE);
    for (const el of document.querySelectorAll("*")) {
      for (const attr of el.attributes) expect(attr.value).not.toContain(VALUE);
      expect(el).not.toHaveAccessibleDescription(escaped);
      // The group and the buttons are named by `label`; nothing is named by the value.
      if (el.matches("[role], button, [aria-label]")) expect(el).not.toHaveAccessibleName(escaped);
    }
    for (const status of within(host).getAllByRole("status"))
      expect(status.textContent).not.toContain(VALUE);
  });

  it.each(["pagehide", "beforeprint", "blur"])(
    "M1: the window's %s masks synchronously, outside act, before dispatchEvent returns",
    async (type) => {
      const host = await render();
      await press(toggle(host));
      const env = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };
      env.IS_REACT_ACT_ENVIRONMENT = false;
      try {
        window.dispatchEvent(new Event(type));
        // No act, no await: the commit already happened.
        expect(stateOf(host)).toBe("masked");
        expect(document.documentElement.outerHTML).not.toContain(VALUE);
        // A second trigger on an already-masked value is a no-op.
        window.dispatchEvent(new Event(type));
        expect(stateOf(host)).toBe("masked");
      } finally {
        env.IS_REACT_ACT_ENVIRONMENT = true;
      }
      expectMasked(host);
    },
  );

  it("M1: a hidden tab masks synchronously, outside act", async () => {
    const host = await render();
    await press(toggle(host));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    const env = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };
    env.IS_REACT_ACT_ENVIRONMENT = false;
    try {
      document.dispatchEvent(new Event("visibilitychange"));
      expect(stateOf(host)).toBe("masked");
    } finally {
      env.IS_REACT_ACT_ENVIRONMENT = true;
    }
  });

  it("N4: no re-mask listener is attached while masked, and none is left after a re-mask", async () => {
    const added = [vi.spyOn(window, "addEventListener"), vi.spyOn(document, "addEventListener")];
    const removed = [
      vi.spyOn(window, "removeEventListener"),
      vi.spyOn(document, "removeEventListener"),
    ];
    const types = (spies: typeof added): string[] =>
      spies.flatMap((spy) => spy.mock.calls.map(([type]) => String(type)));
    const remask = (list: string[]): string[] => list.filter((t) => REMASK_EVENTS.includes(t));
    const host = await render({ copyable: true });
    expect(remask(types(added))).toEqual([]);
    await press(toggle(host));
    expect(remask(types(added)).sort()).toEqual([...REMASK_EVENTS].sort());
    await press(toggle(host));
    expect(remask(types(removed)).sort()).toEqual([...REMASK_EVENTS].sort());
    added.forEach((spy) => spy.mockClear());
    await advance(MASKED_VALUE_AUTO_HIDE_MS * 2);
    await fire(window, "blur");
    expect(remask(types(added))).toEqual([]);
    [...added, ...removed].forEach((spy) => spy.mockRestore());
  });

  it("S1: the handoff lands in the second press's own commit; no commit ever holds two values", async () => {
    const SECOND = "sk-demo-second-9d0e";
    let most = 0;
    const sample = (): void => {
      const html = document.body.innerHTML;
      most = Math.max(most, Number(html.includes(VALUE)) + Number(html.includes(SECOND)));
    };
    const host = await mount(
      <Profiler id="pair" onRender={sample}>
        <MaskedValue value={VALUE} label={LABEL} />
        <MaskedValue value={SECOND} label="API key" />
      </Profiler>,
    );
    await press(toggle(host));
    const env = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };
    env.IS_REACT_ACT_ENVIRONMENT = false;
    try {
      within(host).getByRole("button", { name: "Show API key" }).click();
      // The discrete update flushes in a microtask; one is enough for the whole handoff.
      await Promise.resolve();
      const html = document.body.innerHTML;
      expect(html).toContain(SECOND);
      expect(html).not.toContain(VALUE);
    } finally {
      env.IS_REACT_ACT_ENVIRONMENT = true;
    }
    await act(async () => undefined);
    expect(most).toBe(1);
  });

  it("maskAllValues() from inside an effect: no warning, masked after a microtask", async () => {
    let navigate: (route: string) => void = () => undefined;
    function Router(): JSX.Element {
      const [route, setRoute] = useState("/keys");
      navigate = setRoute;
      useEffect(() => {
        if (route === "/next") maskAllValues();
      }, [route]);
      return <MaskedValue value={VALUE} label={LABEL} />;
    }
    // mount() hands back this test's own container (a portalled echo may sit after it in <body>) and
    // unmounts it after the test, pass or fail.
    const host = await mount(<Router />);
    await press(toggle(host));
    expect(stateOf(host)).toBe("revealed");
    const spies = spyOnConsole();
    try {
      await act(async () => navigate("/next"));
      await act(async () => {
        await Promise.resolve();
      });
      expectMasked(host);
      for (const spy of spies) expect(spy).not.toHaveBeenCalled();
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });

  it("maskAllValues() lands after the caller returns, not before", async () => {
    const host = await render();
    await press(toggle(host));
    const env = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };
    env.IS_REACT_ACT_ENVIRONMENT = false;
    try {
      maskAllValues();
      expect(stateOf(host)).toBe("revealed");
      await Promise.resolve();
      expect(stateOf(host)).toBe("masked");
    } finally {
      env.IS_REACT_ACT_ENVIRONMENT = true;
    }
    expectMasked(host);
  });

  it("a timed re-mask with focus on Copy moves focus to the toggle, never <body>", async () => {
    const host = await render({ copyable: true });
    await press(toggle(host));
    copyButton(host).focus();
    expect(copyButton(host)).toHaveFocus();
    await advance(MASKED_VALUE_AUTO_HIDE_MS);
    expectMasked(host);
    expect(toggle(host)).toHaveFocus();
  });

  it("focus outside the actions is never moved by a re-mask", async () => {
    const outside = document.body.appendChild(document.createElement("button"));
    const host = await render({ copyable: true });
    await press(toggle(host));
    outside.focus();
    await advance(MASKED_VALUE_AUTO_HIDE_MS);
    expectMasked(host);
    expect(outside).toHaveFocus();
  });

  it("StrictMode: a reveal, the auto-hide and the registry handoff behave the same", async () => {
    const onA = fn();
    const host = await mount(
      <StrictMode>
        <MaskedValue value={VALUE} label={LABEL} onToggleReveal={onA} />
        <MaskedValue value="sk-demo-second" label="API key" />
      </StrictMode>,
    );
    const toggleB = (): HTMLElement =>
      within(host).getByRole("button", { name: /^(Show|Hide) API key$/ });
    const states = (): string[] =>
      [...host.querySelectorAll<HTMLElement>(".cv-masked-value")].map(
        (el) => el.dataset["state"] ?? "",
      );
    await press(toggle(host));
    expect(states()).toEqual(["revealed", "masked"]);
    await advance(MASKED_VALUE_AUTO_HIDE_MS);
    expect(states()).toEqual(["masked", "masked"]);
    expect(onA.mock.calls).toEqual([[true], [false]]);
    await press(toggle(host));
    await press(toggleB());
    expect(states()).toEqual(["masked", "revealed"]);
    expect(host.innerHTML).not.toContain(VALUE);
    await act(async () => maskAllValues());
    expect(states()).toEqual(["masked", "masked"]);
    expectValueAbsent();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("slice 8 echo: the toggle and Copy echo their names only, never the value", async () => {
    const host = await render({ copyable: true });
    const echoes = (): HTMLElement[] => [
      ...document.querySelectorAll<HTMLElement>('[role="tooltip"]'),
    ];
    const shownEcho = (): string[] =>
      echoes()
        .filter((el) => !el.hidden)
        .map((el) => el.textContent ?? "");
    await act(async () => toggle(host).focus());
    expect(shownEcho()).toEqual(["Show API secret"]);
    expectValueAbsent();
    await press(toggle(host));
    expect(shownEcho()).toEqual(["Hide API secret"]);
    await act(async () => copyButton(host).focus());
    expect(shownEcho()).toEqual(["Copy API secret"]);
    for (const el of echoes()) {
      expect(el).toHaveAttribute("aria-hidden", "true");
      expect(el.textContent).not.toContain(VALUE);
      for (const attr of el.attributes) expect(attr.value).not.toContain(VALUE);
    }
    await advance(MASKED_VALUE_AUTO_HIDE_MS);
    expect(toggle(host)).toHaveFocus();
    expect(shownEcho()).toEqual(["Show API secret"]);
    expectMasked(host);
  });

  it("S7: unmounting while revealed drops the value, its timers, listeners and registry slot", async () => {
    const host = document.body.appendChild(document.createElement("div"));
    const r = createRoot(host);
    await act(async () => r.render(<MaskedValue value={VALUE} label={LABEL} />));
    await press(toggle(host));
    const removed = vi.spyOn(window, "removeEventListener");
    await act(async () => r.unmount());
    expect(vi.getTimerCount()).toBe(0);
    expect(removed.mock.calls.map(([type]) => type)).toEqual(
      expect.arrayContaining(["blur", "pagehide", "beforeprint", "popstate", "hashchange"]),
    );
    removed.mockRestore();
    expectValueAbsent();
    // The slot is free: a fresh value reveals without touching the gone one.
    const next = await render();
    await press(toggle(next));
    expect(stateOf(next)).toBe("revealed");
  });

  describe("copyable (CMP-033, G19)", () => {
    it("is disabled while masked and never writes", async () => {
      const host = await render({ copyable: true });
      expect(copyButton(host)).toBeDisabled();
      await press(copyButton(host));
      expect(writeText).not.toHaveBeenCalled();
    });

    it("copies the revealed value; the status says Copied only", async () => {
      const host = await render({ copyable: true });
      await press(toggle(host));
      expect(copyButton(host)).toBeEnabled();
      await press(copyButton(host));
      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith(VALUE);
      const statuses = within(host).getAllByRole("status");
      expect(statuses.some((s) => s.textContent === "Copied")).toBe(true);
      for (const s of statuses) expect(s.textContent).not.toContain(VALUE);
    });

    it("is disabled again after the re-mask, with nothing left behind", async () => {
      const host = await render({ copyable: true });
      await press(toggle(host));
      await press(copyButton(host));
      await advance(MASKED_VALUE_AUTO_HIDE_MS);
      expectMasked(host);
      expect(copyButton(host)).toBeDisabled();
      await press(copyButton(host));
      expect(writeText).toHaveBeenCalledTimes(1);
    });

    it("N3: a re-mask mid-copy masks at once; the pending write lands once and says at most Copied", async () => {
      let resolve: () => void = () => undefined;
      writeText.mockImplementation(
        () =>
          new Promise<void>((r) => {
            resolve = r;
          }),
      );
      const host = await render({ copyable: true });
      await press(toggle(host));
      await press(copyButton(host));
      await fire(window, "blur");
      expectMasked(host);
      await act(async () => {
        resolve();
      });
      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith(VALUE);
      expectMasked(host);
      expect(copyButton(host)).toBeDisabled();
      for (const status of within(host).getAllByRole("status"))
        expect(["", "Copied"]).toContain(status.textContent);
    });

    it("N5: the copy status resets with the mask", async () => {
      const host = await render({ copyable: true });
      await press(toggle(host));
      await press(copyButton(host));
      const copied = (): boolean =>
        within(host)
          .getAllByRole("status")
          .some((s) => s.textContent === "Copied");
      expect(copied()).toBe(true);
      await press(toggle(host));
      expect(copied()).toBe(false);
      expect(host.querySelector(".cv-copy-button")?.getAttribute("data-state")).toBe("idle");
    });

    it("density reaches both buttons", async () => {
      const host = await render({ copyable: true, density: "compact" });
      expect(toggle(host).dataset["density"]).toBe("compact");
      expect(copyButton(host).dataset["density"]).toBe("compact");
    });
  });

  it("S5: nothing is logged over the whole lifecycle, a refused copy included", async () => {
    const spies = spyOnConsole();
    try {
      const host = await render({ copyable: true });
      await press(toggle(host));
      await press(copyButton(host));
      writeText.mockRejectedValue(new Error(VALUE));
      await advance(2000);
      await press(copyButton(host));
      await advance(MASKED_VALUE_AUTO_HIDE_MS);
      await press(toggle(host));
      // Keyboard focus on each control: the slice 8 name echo shows and hides inside act.
      await act(async () => toggle(host).focus());
      await act(async () => copyButton(host).focus());
      await fire(window, "blur");
      await act(async () => toggle(host).blur());
      for (const spy of spies) expect(spy).not.toHaveBeenCalled();
      expect(spies.length).toBeGreaterThan(5);
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });
});
