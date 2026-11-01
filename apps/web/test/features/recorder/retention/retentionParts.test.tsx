/**
 * E16-S03 (#485), SCR-141's parts (E16-D03 §2 (b), (d), §7, §1.3; E16-D06 KB-10, T2-06, T2-07, FM-11, F-10): the
 * global rows, the pinned list, the error summary and Apply's validity look, each on its own, over the `22`
 * examples. The dialog that composes them is `RetentionEditor.test.tsx`'s.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createRef, useState, type JSX } from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { GatedAnnounceProvider } from "@candleviewer/ui";
import { ErrorSummary } from "../../../../src/features/recorder/retention/ErrorSummary";
import {
  GlobalDefaults,
  type GlobalDefaultsProps,
} from "../../../../src/features/recorder/retention/GlobalDefaults";
import { PinnedList } from "../../../../src/features/recorder/retention/PinnedList";
import {
  load,
  resetToDefault,
  setAction,
  setDays,
  type Draft,
  type DraftRow,
} from "../../../../src/features/recorder/retention/retentionModel";
import { ValidityButton } from "../../../../src/features/recorder/retention/ValidityButton";
import { POLICIES_DEFAULTS, STORAGE_USAGE } from "./fixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };
async function serious(element: Element): Promise<unknown[]> {
  const res = await axe.run(element, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

beforeAll(() => {
  // CMP-009 keeps its active option in view; jsdom lays nothing out.
  Element.prototype.scrollIntoView = vi.fn();
});

// A cold first mount takes seconds on a loaded host; role queries over eight rows of controls are slow in jsdom.
const CASE = { timeout: 20_000 } as const;

const globals = (draft: Draft): readonly DraftRow[] =>
  draft.rows.filter((row) => row.symbol === null);
const BASE = load(POLICIES_DEFAULTS.items);

/** The rows, kept in state as the dialog keeps them, with every call recorded. */
function Host(props: { readonly draft?: Draft; readonly gate?: GlobalDefaultsProps["gate"] }) {
  const [draft, setDraft] = useState(props.draft ?? BASE);
  return (
    <GatedAnnounceProvider announce={say}>
      <p id="notice">Read-only while viewing as alex.</p>
      <GlobalDefaults
        rows={globals(draft)}
        fieldId={(stream) => `field-${stream}`}
        gate={props.gate ?? null}
        onDays={(stream, n) => {
          calls.push(["days", stream, n]);
          setDraft((d) => setDays(d, { symbol: null, stream }, n));
        }}
        onAction={(stream, action) => {
          calls.push(["action", stream, action]);
          setDraft((d) => setAction(d, { symbol: null, stream }, action));
        }}
        onReset={(stream) => {
          calls.push(["reset", stream]);
          setDraft((d) => resetToDefault(d, stream));
        }}
      />
    </GatedAnnounceProvider>
  );
}
let calls: unknown[][] = [];
let say = vi.fn<(text: string) => void>();
const reset = () => {
  calls = [];
  say = vi.fn();
};
const row = (name: string): HTMLElement => screen.getByRole("group", { name });
const field = (name: string): HTMLInputElement =>
  within(row(name)).getByRole("spinbutton") as HTMLInputElement;
const typeIn = (input: HTMLInputElement, text: string): void => {
  act(() => input.focus());
  fireEvent.change(input, { target: { value: text } });
  fireEvent.blur(input);
};

describe("region (b): the global rows (D03 §2 (b), §3; KB-10)", CASE, () => {
  it("eight rows in the contract's order, each a group named by its stream, on the 22 set", () => {
    reset();
    render(<Host />);
    const section = screen.getByRole("group", { name: "Global defaults" });
    const names = within(section)
      .getAllByRole("group")
      .map((g) => document.getElementById(g.getAttribute("aria-labelledby") ?? "")?.textContent);
    expect(names).toEqual([
      "Trades",
      "Order-book deltas",
      "Order-book snapshots",
      "Tickers",
      "Exchange klines",
      "Liquidations",
      "Open interest",
      "Funding rates",
    ]);
    expect(
      screen
        .getAllByRole("spinbutton")
        .map((input) => [input.getAttribute("aria-valuetext"), input.id]),
    ).toEqual([
      ["30 days", "field-trades"],
      ["7 days", "field-orderbook_delta"],
      ["30 days", "field-orderbook_snapshot"],
      ["30 days", "field-tickers"],
      ["90 days", "field-klines"],
      ["90 days", "field-liquidations"],
      ["90 days", "field-open_interest"],
      ["365 days", "field-funding"],
    ]);
    expect(screen.getByRole("spinbutton", { name: "Trades Retention (days)" })).toHaveValue("30");
  });

  it("a row on its seed: Move to Parquet after, the horizon, the chip and the help (editing-clean)", () => {
    reset();
    render(<Host />);
    const trades = row("Trades");
    expect(within(trades).getByRole("combobox", { name: "Trades Action" })).toHaveTextContent(
      "Move to Parquet after",
    );
    expect(trades).toHaveTextContent("Kept in Parquet until 24 months");
    expect(trades).toHaveTextContent("Default 30 d");
    expect(within(trades).queryByRole("button", { name: "Reset to default" })).toBeNull();
    expect(field("Trades")).toHaveAccessibleDescription(
      expect.stringContaining(
        "Days in the fast store before the nightly move to Parquet. Parquet keeps it for 24 months in total. " +
          "Bars, footprints and profiles are rebuilt from trades, so trades must be kept at least as long as them.",
      ),
    );
    expect(row("Exchange klines")).toHaveTextContent("Kept in Parquet with no end date");
    expect(row("Funding rates")).toHaveTextContent("Default 365 d");
  });

  it("a typed value commits on blur; the arrows step a day, Page keys ten (CMP-008)", () => {
    reset();
    render(<Host />);
    typeIn(field("Trades"), "7");
    expect(calls).toEqual([["days", "trades", 7]]);
    fireEvent.keyDown(field("Trades"), { key: "ArrowUp" });
    fireEvent.keyDown(field("Trades"), { key: "PageUp" });
    expect(calls.slice(1)).toEqual([
      ["days", "trades", 8],
      ["days", "trades", 18],
    ]);
  });

  it("an edited row trades its chip for Reset to default, which puts the seed back", () => {
    reset();
    render(<Host />);
    typeIn(field("Trades"), "90");
    const resetButton = within(row("Trades")).getByRole("button", { name: "Reset to default" });
    expect(row("Trades")).not.toHaveTextContent("Default 30 d");
    fireEvent.click(resetButton);
    expect(calls.at(-1)).toEqual(["reset", "trades"]);
    expect(row("Trades")).toHaveTextContent("Default 30 d");
  });

  it.each([
    ["0", "Keep at least 1 day."],
    ["4000", "At most 3650 days (10 years)."],
  ])(
    "%s days shows %s in product words and marks the field (SCR-141/field-min, field-max)",
    (typed, line) => {
      reset();
      render(<Host />);
      typeIn(field("Trades"), typed);
      expect(field("Trades")).toHaveAttribute("aria-invalid", "true");
      expect(row("Trades")).toHaveTextContent(line);
      expect(field("Trades")).toHaveAccessibleDescription(expect.stringContaining(line));
    },
  );

  it("the tracks fit the stepper with four digits and 'Move to Parquet after', and shrink to the section (A-5353-04, -09)", () => {
    reset();
    render(<Host />);
    // Measured in Chromium: five tracks to the 960 px dialog at both densities, one at a 320 px viewport.
    const tracks = (row("Trades").firstElementChild as HTMLElement).style.gridTemplateColumns;
    expect(tracks).toBe("repeat(auto-fill, minmax(min(10.75rem, 100%), 1fr))");
  });

  it("a Delete-after row in error states no horizon until it is valid (C-5353-14)", () => {
    reset();
    render(<Host draft={setAction(BASE, { symbol: null, stream: "trades" }, "drop")} />);
    expect(row("Trades")).toHaveTextContent("Kept in Parquet until 30 days");
    typeIn(field("Trades"), "0");
    expect(row("Trades")).toHaveTextContent("Keep at least 1 day.");
    expect(row("Trades")).not.toHaveTextContent("Kept in Parquet until");
    typeIn(field("Trades"), "1");
    expect(row("Trades")).toHaveTextContent("Kept in Parquet until 1 day");
  });

  it("7.5 days: CMP-008 rounds a typed value to whole days and says so (precision 0)", () => {
    reset();
    render(<Host />);
    typeIn(field("Trades"), "7.5");
    expect(calls).toEqual([["days", "trades", 8]]);
    expect(field("Trades")).not.toHaveAttribute("aria-invalid");
  });

  it("Delete after: the help switches; a stream without roll-off its own; no other source warns", () => {
    reset();
    const draft = [
      (d: Draft) => setAction(d, { symbol: null, stream: "trades" }, "drop"),
      (d: Draft) => setAction(d, { symbol: null, stream: "orderbook_snapshot" }, "drop"),
      (d: Draft) => setAction(d, { symbol: null, stream: "klines" }, "drop"),
      (d: Draft) => setAction(d, { symbol: null, stream: "liquidations" }, "drop"),
    ].reduce((d, step) => step(d), BASE);
    render(<Host draft={draft} />);
    expect(field("Trades")).toHaveAccessibleDescription(
      expect.stringContaining(
        "Days before this stream's data is deleted for good, Parquet included.",
      ),
    );
    expect(field("Order-book snapshots")).toHaveAccessibleDescription(
      expect.stringContaining(
        "Days before this stream's Parquet copy is deleted for good. The fast store keeps its rows.",
      ),
    );
    expect(row("Exchange klines")).toHaveTextContent("This stream has no other source.");
    expect(row("Liquidations")).toHaveTextContent(
      "Irreplaceable: there is no history to fetch again.",
    );
    expect(row("Trades")).not.toHaveTextContent("no other source");
  });

  it("the Action select offers the contract's two actions in the deck's words (downsample, pin absent)", () => {
    reset();
    render(<Host />);
    fireEvent.click(screen.getByRole("combobox", { name: "Trades Action" }));
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Move to Parquet after", "Delete after"]);
    fireEvent.click(screen.getByRole("option", { name: "Delete after" }));
    expect(calls).toEqual([["action", "trades", "drop"]]);
  });

  it("view-as: every write is T2 with its full label; a step changes nothing (T2-06, D03 §1.3)", () => {
    reset();
    const reason = "Read-only while viewing as alex.";
    render(
      <Host
        draft={setDays(BASE, { symbol: null, stream: "tickers" }, 7)}
        gate={{ reason, noticeId: "notice" }}
      />,
    );
    for (const input of screen.getAllByRole("spinbutton")) {
      expect(input).toHaveAttribute("aria-disabled", "true");
      expect(input).toHaveAccessibleDescription(reason);
    }
    const resetButton = within(row("Tickers")).getByRole("button", {
      name: "Not available Reset to default",
    });
    expect(resetButton).toHaveAttribute("aria-disabled", "true");
    expect(resetButton).toHaveAccessibleDescription(reason);
    fireEvent.keyDown(field("Trades"), { key: "ArrowUp" });
    fireEvent.click(resetButton);
    expect(calls).toEqual([]);
    expect(say).toHaveBeenCalledWith(reason);
  });

  it("has no serious axe violation, clean and in error", async () => {
    reset();
    const { container } = render(
      <Host draft={setDays(BASE, { symbol: null, stream: "trades" }, 0)} />,
    );
    expect(await serious(container)).toEqual([]);
  });
});

describe("region (d): the pinned list (D03 §9 SCR-141/pinned-list; BQ-5, BQ-6)", CASE, () => {
  it("BTCUSDT with its glyph, size, the exempt word and its growth; Manage pin reaches the row detail", () => {
    const onManage = vi.fn();
    render(<PinnedList storage={STORAGE_USAGE} onManage={onManage} />);
    const list = screen.getByRole("region", { name: "Pinned symbols (exempt)" });
    expect(list).toHaveAccessibleDescription(
      "Pinned symbols are never deleted by retention. Unpin a symbol in the Recorder to let its data follow the policy; the Recorder states the volume that becomes eligible.",
    );
    const [item] = within(list).getAllByRole("listitem");
    expect(item).toHaveTextContent(
      "BTCUSDT· 812.3 GB· Exempt (pinned)· grows about 780 MB/dayManage pin in Recorder",
    );
    expect(within(list).getByRole("img", { name: "Pinned" })).toBeInTheDocument();
    expect(within(list).queryByText("ETHUSDT")).toBeNull();
    const manage = within(list).getByRole("button", { name: "Manage pin in Recorder" });
    expect(manage).toHaveAccessibleDescription("BTCUSDT");
    fireEvent.click(manage);
    expect(onManage).toHaveBeenCalledWith("BTCUSDT");
  });

  it("the editor's exempt symbols: a pin the report does not list has no size; one the frame unpinned is gone", () => {
    render(<PinnedList storage={STORAGE_USAGE} pinned={["XRPUSDT"]} />);
    const [item] = within(screen.getByRole("region")).getAllByRole("listitem");
    expect(item).toHaveTextContent(/^XRPUSDT· Exempt \(pinned\)$/);
    expect(screen.queryByText("BTCUSDT")).toBeNull();
  });

  it("no row detail registered: no link; no pinned symbol: 'No pinned symbols.' (no unpin control)", () => {
    const { rerender } = render(<PinnedList storage={STORAGE_USAGE} />);
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<PinnedList storage={{ ...STORAGE_USAGE, symbols: [] }} />);
    expect(screen.getByText("No pinned symbols.")).toBeVisible();
  });

  it("has no serious axe violation", async () => {
    const { container } = render(<PinnedList storage={STORAGE_USAGE} onManage={() => undefined} />);
    expect(await serious(container)).toEqual([]);
  });
});

describe("the error summary (D03 §7 SCR-141/error-summary; F-10, FM-11)", CASE, () => {
  it("a heading that takes focus and links to each field; no alert role, no live region", () => {
    const heading = createRef<HTMLHeadingElement>();
    const { container } = render(
      <>
        <input id="field-trades" aria-label="Trades Retention (days)" />
        <ErrorSummary
          title="Fix 1 field before applying."
          links={[
            { label: "Trades · Retention (days): Keep at least 1 day.", targetId: "field-trades" },
          ]}
          headingRef={heading}
        />
      </>,
    );
    expect(screen.getByRole("heading", { level: 3, name: "Fix 1 field before applying." })).toBe(
      heading.current,
    );
    expect(container.querySelector('[role="alert"], [aria-live]')).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Trades · Retention (days): Keep at least 1 day." }),
    );
    expect(screen.getByRole("textbox", { name: "Trades Retention (days)" })).toHaveFocus();
  });
});

describe(
  "Apply's validity look (D03 §1.3; T2-07): the seam for #484 PR 3's CMP-001 look",
  CASE,
  () => {
    function Apply(props: { readonly reason?: string; readonly gate?: string }): JSX.Element {
      return (
        <GatedAnnounceProvider announce={say}>
          <p id="notice">{props.gate}</p>
          <ValidityButton
            reasonId="reason"
            reason={props.reason}
            onPress={() => calls.push(["press"])}
            onRefused={() => calls.push(["refused"])}
            {...(props.gate === undefined
              ? {}
              : { disabledReason: props.gate, disabledReasonId: "notice" })}
          >
            Apply
          </ValidityButton>
          <span id="reason">{props.reason}</span>
        </GatedAnnounceProvider>
      );
    }

    it("ready: a press is the action", () => {
      reset();
      render(<Apply />);
      fireEvent.click(screen.getByRole("button", { name: "Apply" }));
      expect(calls).toEqual([["press"]]);
    });

    it("not ready: a Tab stop described by its reason; a press is the refusal, never the action", () => {
      reset();
      render(<Apply reason="Preview the change first." />);
      const apply = screen.getByRole("button", { name: "Apply" });
      expect(apply).toHaveAccessibleDescription("Preview the change first.");
      expect(apply).not.toHaveAttribute("disabled");
      fireEvent.click(apply);
      expect(calls).toEqual([["refused"]]);
    });

    it("view-as wins: T2 with the lock and the notice; a press does nothing and says the reason once", () => {
      reset();
      const reason = "Read-only while viewing as alex.";
      render(<Apply reason="No changes to apply." gate={reason} />);
      const apply = screen.getByRole("button", { name: "Not available Apply" });
      expect(apply).toHaveAttribute("aria-disabled", "true");
      expect(apply).toHaveAccessibleDescription(reason);
      fireEvent.click(apply);
      expect(calls).toEqual([]);
      expect(say.mock.calls).toEqual([[reason]]);
    });
  },
);
