// @vitest-environment jsdom
import { act, type JSX, type SetStateAction } from "react";
import type * as ReactModule from "react";
import { createRoot } from "react-dom/client";
import { fireEvent } from "storybook/test";
import { afterEach, expect, it, vi } from "vitest";
import { Combobox, SymbolSearchInput, type ComboboxOption } from "../src/index.js";

/**
 * React drops a state update on an unmounted component without a word, so this file counts updates: every
 * `useState` setter is wrapped, and an update made once `after` is set is a late one.
 */
const late = vi.hoisted(() => ({ after: false, updates: 0 }));
vi.mock("react", async (importOriginal) => {
  const react = await importOriginal<typeof ReactModule>();
  function useState<S>(initial: S | (() => S)): readonly [S, (next: SetStateAction<S>) => void] {
    const [state, set] = react.useState(initial);
    const counted = react.useCallback(
      (next: SetStateAction<S>): void => {
        if (late.after) late.updates += 1;
        set(next);
      },
      [set],
    );
    return [state, counted];
  }
  return { ...react, useState };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
// A failed assertion must not leave fake timers to the next test.
afterEach(() => {
  vi.useRealTimers();
});

it("an unmount aborts the search in flight, and its late answer sets no state", async () => {
  const flight: {
    query?: string;
    signal?: AbortSignal;
    answer?: (options: readonly ComboboxOption[]) => void;
  } = {};
  const search = (query: string, signal: AbortSignal): Promise<readonly ComboboxOption[]> =>
    new Promise((answer) => Object.assign(flight, { query, signal, answer }));
  const root = createRoot(document.body.appendChild(document.createElement("div")));
  await act(async () =>
    root.render(
      <Combobox
        aria-label="Symbol"
        value="btc"
        onChange={() => undefined}
        asyncSearch={search}
        noResultsText="No USDT perpetual matches the query."
        searchFailedText="Couldn't load the instrument list."
      />,
    ),
  );
  const input = document.querySelector("input") ?? document.body;
  await act(async () => {
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
  });
  expect([flight.query, flight.signal?.aborted]).toEqual(["btc", false]);
  await act(async () => root.unmount());
  expect(flight.signal?.aborted).toBe(true);
  late.after = true;
  await act(async () => flight.answer?.([{ value: "btc", label: "BTCUSDT" }]));
  expect(late.updates).toBe(0);
});

const noop = (): void => undefined;
it.each<[string, () => JSX.Element]>([
  [
    "CMP-048",
    () => <Combobox aria-label="Symbol" options={[]} value="b" onChange={noop} settleMs={300} />,
  ],
  ["CMP-160", () => <SymbolSearchInput value="b" onChange={noop} onSelect={noop} items={[]} />],
])("%s: a settle still pending at unmount sets no state when its time comes", async (_id, ui) => {
  vi.useFakeTimers();
  late.after = false;
  late.updates = 0;
  const root = createRoot(document.body.appendChild(document.createElement("div")));
  await act(async () => root.render(ui()));
  await act(
    async () =>
      void fireEvent.change(document.querySelector("input") ?? document.body, {
        target: { value: "bt" },
      }),
  );
  expect(vi.getTimerCount()).toBeGreaterThan(0); // the settle is pending
  await act(async () => root.unmount());
  late.after = true;
  await act(async () => vi.advanceTimersByTimeAsync(1000).then(noop));
  expect([late.updates, vi.getTimerCount()]).toEqual([0, 0]);
});
