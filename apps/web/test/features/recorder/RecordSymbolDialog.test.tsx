/**
 * E16-S01, "Record a symbol" (E16-D02 §6.1, §6.4's step-up; E16-D06 KB-05, T2-02, FM-04, §16.4 rows 2, 4 and 5)
 * over a stubbed `apiFetch` (no network, C-13.5), on the `22` examples' clock (the step-up fixture's challenge is
 * five minutes on). Presses are `fireEvent`s: a browser's click on a focused button, and a held key's repeat as a
 * keydown with `repeat: true`.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState, type JSX } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { GatedAnnounceProvider } from "@candleviewer/ui";
import {
  RecordSymbolDialog,
  type RecordSymbolDialogProps,
} from "../../../src/features/recorder/RecordSymbolDialog";
import { addManual, problem, stepUpRequired } from "./fixtures";
import { D02_ROWS, NOW } from "./gridFixtures";
import { POLICY } from "./modelFixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const CAP = "The symbol limit is reached.";
const reply = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const sent = (n = 0) => {
  const [url, init] = apiFetch.mock.calls[n] ?? [];
  const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
  return {
    url,
    method: init?.method,
    body,
    idemp: new Headers(init?.headers).get("Idempotency-Key"),
  };
};
const settle = () => act(async () => void (await Promise.resolve()));
const button = (name: string | RegExp): HTMLButtonElement =>
  screen.getByRole("button", { name }) as HTMLButtonElement;
const dialog = (): HTMLElement => screen.getByRole("dialog", { name: "Record a symbol" });
const symbolBox = (): HTMLInputElement =>
  within(dialog()).getByRole("combobox", { name: "Symbol" }) as HTMLInputElement;
const type = (value: string): void => void fireEvent.change(symbolBox(), { target: { value } });
/** A press as a browser makes it: focus, then the click. */
const press = (control: HTMLElement): void => {
  act(() => control.focus());
  fireEvent.click(control);
};

let say = vi.fn<(text: string) => void>();
function Host(props: Partial<RecordSymbolDialogProps>): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <GatedAnnounceProvider announce={say}>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <RecordSymbolDialog
        open={open}
        onClose={() => setOpen(false)}
        rows={D02_ROWS}
        policy={POLICY}
        instruments={["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]}
        onAdded={() => undefined}
        readBack={() => undefined}
        {...props}
      />
    </GatedAnnounceProvider>
  );
}
const open = (props: Partial<RecordSymbolDialogProps> = {}) => {
  const view = render(<Host {...props} />);
  press(button("Open"));
  return view;
};

let reported: unknown[] = [];
const onAnalytics = (event: Event): void => void reported.push((event as CustomEvent).detail);
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  say = vi.fn();
  reported = [];
  window.addEventListener("cv:analytics", onAnalytics);
});
afterEach(() => {
  window.removeEventListener("cv:analytics", onAnalytics);
  apiFetch.mockReset();
  vi.useRealTimers();
});

describe("Record a symbol (D02 §6.1; KB-05)", () => {
  // The file's first render pays jsdom's and the dialog's warm-up: 1.3 s alone, 7.7 s at load 39.
  it("opens on the Symbol combobox with §6.1's defaults and help", { timeout: 15_000 }, () => {
    open();
    expect(symbolBox()).toHaveFocus();
    // The field's empty error line leads its description (CMP-040), so the help is matched within it.
    expect(symbolBox()).toHaveAccessibleDescription(
      /A slot frees when a symbol stops, up to 30 min after its last reason ends\./,
    );
    const streams = ["Trades", "Order-book deltas", "Tickers", "Liquidations", "Klines"].map(
      (name) => (within(dialog()).getByRole("checkbox", { name }) as HTMLInputElement).checked,
    );
    expect(streams).toEqual([true, true, true, true, false]);
    expect(within(dialog()).getByRole("radio", { name: "200" })).toBeChecked();
    expect(within(dialog()).getByText(/^About 0\.5–0\.75 GB a day at depth 200/)).toBeVisible();
    expect(within(dialog()).getByRole("spinbutton", { name: "Retention" })).toHaveValue("30");
    expect(within(dialog()).getByRole("switch", { name: "Keep forever" })).not.toBeChecked();
  });

  it("Enter in the combobox picks the active option, never submits (C-5309-13)", () => {
    Element.prototype.scrollIntoView = vi.fn(); // the active option scrolls into view; jsdom has no layout
    open();
    type("sol");
    fireEvent.keyDown(symbolBox(), { key: "ArrowDown" }); // an arrow opens the list at once
    fireEvent.keyDown(symbolBox(), { key: "Enter" });
    expect(symbolBox()).toHaveValue("SOLUSDT");
    expect(apiFetch).not.toHaveBeenCalled();
    expect(dialog()).toBeInTheDocument();
  });

  it("Start recording sends the add, closes, returns focus to the opener and reports it", async () => {
    const onAdded = vi.fn();
    apiFetch.mockResolvedValueOnce(
      reply(201, { id: "e1-sol", symbol: "SOLUSDT", reason: "manual", state: "starting" }),
    );
    open({ onAdded });
    type("solusdt");
    press(button("Start recording"));
    await settle();
    expect(sent()).toMatchObject({
      url: "/api/v1/recording/symbols",
      method: "POST",
      body: addManual,
    });
    expect(onAdded).toHaveBeenCalledWith(expect.objectContaining({ symbol: "SOLUSDT" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(button("Open")).toHaveFocus();
    expect(reported).toEqual([
      {
        name: "recorder.symbol_added",
        symbol: "SOLUSDT",
        depth: 200,
        streams: ["trades", "orderbook_delta", "tickers", "liquidations"],
        retentionDays: 30,
        pinned: false,
      },
    ]);
  });

  it("Cancel closes it, sends nothing and returns focus to the opener (FM-04)", () => {
    open();
    press(button("Cancel"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(button("Open")).toHaveFocus();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("a second opening shows §6.1's defaults from its first frame, as focus lands (#5309)", () => {
    open();
    type("solusdt");
    press(within(dialog()).getByRole("switch", { name: "Keep forever" }));
    press(button("Cancel"));
    // What the opening shows as focus lands on the Symbol field: its first frame, before any effect has run.
    const landed: string[] = [];
    const onFocus = (event: FocusEvent): void => {
      if (!(event.target instanceof HTMLInputElement)) return;
      const keep = document.querySelector('[role="switch"]');
      const on =
        keep instanceof HTMLInputElement ? keep.checked : keep?.getAttribute("aria-checked");
      landed.push(`${event.target.value}|keep forever ${String(on)}`);
    };
    document.addEventListener("focus", onFocus, true);
    press(button("Open"));
    document.removeEventListener("focus", onFocus, true);
    expect(landed).toEqual(["|keep forever false"]);
    expect(symbolBox()).toHaveFocus();
    expect(symbolBox()).toHaveValue("");
  });
});

describe("the recorder step-up on a pinned add (D02 §6.4; §16.4 row 5)", () => {
  it("Keep forever meets SCR-006; Esc drops it: Not sent, the inputs kept, focus back on Start recording", async () => {
    apiFetch.mockResolvedValueOnce(reply(403, stepUpRequired));
    open();
    type("SOLUSDT");
    fireEvent.click(within(dialog()).getByRole("switch", { name: "Keep forever" }));
    expect(within(dialog()).queryByRole("spinbutton", { name: "Retention" })).toBeNull();
    const start = button("Start recording");
    press(start);
    await settle();
    expect(sent().body).toMatchObject({ symbol: "SOLUSDT", pinned: true, retention_days: null });
    const challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
    expect(challenge).toHaveTextContent("Keep BTCUSDT data forever");
    fireEvent.keyDown(within(challenge).getByLabelText("Password"), { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(dialog()).toHaveTextContent("Not sent");
    expect(symbolBox()).toHaveValue("SOLUSDT");
    expect(start).toHaveFocus();
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("a granted step-up re-sends the held add once with its key; the dialog closes on the answer", async () => {
    const onAdded = vi.fn();
    apiFetch
      .mockResolvedValueOnce(reply(403, stepUpRequired))
      .mockResolvedValueOnce(reply(200, { action_class: "recorder" }))
      .mockResolvedValueOnce(
        reply(201, {
          id: "e1-sol",
          symbol: "SOLUSDT",
          reason: "manual",
          state: "starting",
          pinned: true,
        }),
      );
    open({ onAdded });
    type("SOLUSDT");
    fireEvent.click(within(dialog()).getByRole("switch", { name: "Keep forever" }));
    press(button("Start recording"));
    await settle();
    const challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
    fireEvent.change(within(challenge).getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(within(challenge).getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    fireEvent.click(within(challenge).getByRole("button", { name: "Confirm" }));
    await settle();
    await settle();
    await settle();
    expect(sent(1).url).toBe("/api/v1/auth/step-up");
    expect(sent(2)).toMatchObject({ url: "/api/v1/recording/symbols", method: "POST" });
    expect(sent(2).idemp).toBe(sent(0).idemp);
    expect(sent(2).body).toEqual(sent(0).body);
    expect(onAdded).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("while its add is on the wire (H22; S-5347-d01)", () => {
  it("Cancel, ✕ and Esc keep the dialog, so a challenge is never parked under a later opening; the answer closes it", async () => {
    let release: (response: Response) => void = () => undefined;
    apiFetch.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    const onAdded = vi.fn();
    open({ onAdded });
    type("SOLUSDT");
    press(button("Start recording"));
    await settle();
    press(button("Cancel"));
    expect(dialog()).toBeInTheDocument();
    press(button("Close Record a symbol"));
    expect(dialog()).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(dialog()).toBeInTheDocument();
    release(reply(201, { id: "e1-sol", symbol: "SOLUSDT", reason: "manual", state: "starting" }));
    await settle();
    await settle();
    expect(onAdded).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });
});

describe("refusals (T2-02; §16.4 rows 2 and 4)", () => {
  const four = { ...POLICY, max_symbols: 4 };

  it("at the limit, Start recording is T2 for a symbol outside the active rows; a press sends nothing", () => {
    open({ policy: four });
    type("DOGEUSDT");
    const start = button("Not available Start recording");
    expect(start).toHaveAttribute("aria-disabled", "true");
    expect(start).toHaveAccessibleDescription(CAP);
    expect(within(dialog()).getByText(CAP)).toBeVisible();
    press(start);
    expect(fireEvent.keyDown(start, { key: "Enter", repeat: true })).toBe(false);
    expect(say.mock.calls).toEqual([[CAP]]);
    expect(apiFetch).not.toHaveBeenCalled();
    // An active symbol only gains `manual` (D02 §2): never at the limit.
    type("BTCUSDT");
    expect(button("Start recording")).not.toHaveAttribute("aria-disabled");
  });

  it("a 422 shows under its field with its code; the problem's words never show", async () => {
    const body = problem(422, "validation_failed", {
      errors: [{ field: "symbol", rule: "unlisted", message: "server message" }],
    });
    apiFetch.mockResolvedValueOnce(reply(422, body));
    open();
    type("ZZZUSDT");
    press(button("Start recording"));
    await settle();
    const words = "Not started: the server refused it. (validation_failed)";
    expect(symbolBox()).toHaveAccessibleDescription(expect.stringContaining(words));
    expect(dialog()).not.toHaveTextContent("server message");
    expect(dialog()).not.toHaveTextContent("server detail");
    expect(button("Start recording")).not.toHaveAttribute("aria-busy");
  });

  it("a refusal no field owns shows above the footer, its region there from the start", async () => {
    apiFetch.mockResolvedValueOnce(reply(422, problem(422, "recorder_symbol_limit")));
    open();
    const region = within(dialog()).getAllByRole("status").at(-1) as HTMLElement;
    expect(region).toBeEmptyDOMElement();
    type("DOGEUSDT");
    press(button("Start recording"));
    await settle();
    expect(region).toHaveTextContent("Not started: the server refused it. (recorder_symbol_limit)");
  });
});

it("has no serious axe violation, open", { timeout: 20_000 }, async () => {
  open();
  vi.useRealTimers();
  const res = await axe.run(dialog(), { rules: { "color-contrast": { enabled: false } } });
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
});
