import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { useState, type JSX } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { GatedAnnounceProvider } from "@candleviewer/ui";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import {
  BudgetGrid,
  ConnectivityActions,
  ChangeBudgetDialog,
  ReconnectDialog,
  StateTile,
  type ActionGate,
} from "../../../src/features/admin-connectivity/components";
import { COPY, SAVE_BUDGET } from "../../../src/features/admin-connectivity/copy";
import { SERVED_REPORT } from "../../../src/features/admin-connectivity/fixtures";
import { rateBudgetRows } from "../../../src/features/admin-connectivity/rateBudget";
import { STATE_IDS } from "../../../src/features/admin-connectivity/states";

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
  clearAnnouncements();
  vi.unstubAllGlobals();
});

const noop = (): void => undefined;
const live = (container: HTMLElement, politeness: "polite" | "assertive"): HTMLElement => {
  const el = container.querySelector<HTMLElement>(`[aria-live="${politeness}"]`);
  if (el === null) throw new Error(`no ${politeness} region`);
  return el;
};

/** As the shell mounts it: the ui package's own announcement is a no-op, and the shell's pair is the only region. */
function InShell({ gate }: { readonly gate: ActionGate }): JSX.Element {
  return (
    <GatedAnnounceProvider announce={noop}>
      <ShellAnnouncer />
      <ConnectivityActions gate={gate} onReconnect={noop} onChangeBudget={noop} />
    </GatedAnnounceProvider>
  );
}

describe("G-T2.3: a gated press re-shows its reason and says it once, politely", () => {
  it("under the hold: aria-disabled, focusable, reason described, one polite line per press", () => {
    const { container } = render(<InShell gate={{ kind: "hold" }} />);
    const button = screen.getByRole("button", { name: /Reconnect market data/ });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    button.focus();
    expect(button).toHaveFocus();
    expect(button).toHaveAccessibleDescription(/All requests are on hold\./);
    // Enter and Space reach a native button as a click.
    fireEvent.click(button);
    expect(live(container, "polite")).toHaveTextContent("All requests are on hold.");
    expect(live(container, "polite").querySelectorAll("p")).toHaveLength(1);
    expect(live(container, "assertive")).toBeEmptyDOMElement();
    const first = live(container, "polite").querySelector("p")?.getAttribute("data-seq");
    fireEvent.click(button);
    expect(live(container, "polite").querySelectorAll("p")).toHaveLength(1);
    expect(live(container, "polite").querySelector("p")?.getAttribute("data-seq")).not.toBe(first);
  });

  // jsdom cannot synthesise the native click a held Enter fires, so only the default-prevented keydown is proved
  // here, and it is the ui Button atom's guard, not this component's; measured pass owed to PR-2 (Playwright).
  it("the page's gated button, as mounted, has a repeated Enter's default prevented (atom guard)", () => {
    render(<InShell gate={{ kind: "hold" }} />);
    const button = screen.getByRole("button", { name: /Reconnect market data/ });
    const repeat = fireEvent.keyDown(button, { key: "Enter", repeat: true });
    expect(repeat).toBe(false); // default prevented: the native click is swallowed
  });

  it("the connection budget names its wait from a served count, not a typed one", () => {
    render(<InShell gate={{ kind: "wait", seconds: 40 }} />);
    expect(
      screen.getByRole("button", { name: /Reconnect market data/ }),
    ).toHaveAccessibleDescription("Wait 40 s. The connection budget allows no new connection yet.");
    expect(screen.getByRole("button", { name: /Change budget/ })).not.toHaveAttribute(
      "aria-disabled",
    );
  });

  it("an open gate is a plain, enabled button", () => {
    render(<InShell gate={{ kind: "open" }} />);
    expect(screen.getByRole("button", { name: /Reconnect market data/ })).not.toHaveAttribute(
      "aria-disabled",
    );
  });
});

describe("G-T2.5: one read-only panel notice", () => {
  it("under view-as both writes point at one notice, which is not live", () => {
    const { container } = render(<InShell gate={{ kind: "view_as", user: "Alex" }} />);
    const sentence = "Read-only while viewing as Alex.";
    expect(screen.getAllByText(sentence)).toHaveLength(1);
    const buttons = [
      screen.getByRole("button", { name: /Reconnect market data/ }),
      screen.getByRole("button", { name: /Change budget/ }),
    ];
    const ids = new Set(buttons.map((b) => b.getAttribute("aria-describedby")));
    expect(ids.size).toBe(1);
    for (const b of buttons) {
      expect(b).toHaveAttribute("aria-disabled", "true");
      expect(b).toHaveAccessibleDescription(sentence);
    }
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.querySelectorAll('[role="status"]')).toHaveLength(0);
  });
});

describe("R3: focus returns from the dialog to its trigger", () => {
  function Host(): JSX.Element {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Open it
        </button>
        <ReconnectDialog
          open={open}
          connections={3}
          topics={120}
          onConfirm={() => setOpen(false)}
          onCancel={() => setOpen(false)}
        />
      </>
    );
  }

  it("opens an alertdialog on Cancel and gives focus back on cancel", async () => {
    render(<Host />);
    const trigger = screen.getByRole("button", { name: "Open it" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(COPY["W-55"])).toBeInTheDocument(); // the marker, label only
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus(),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("keeps Confirm unavailable until the blast radius has loaded", async () => {
    render(
      <ReconnectDialog open connections={null} topics={null} onConfirm={noop} onCancel={noop} />,
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("button", { name: COPY["W-50"] })).toBeDisabled();
  });
});

describe("ChangeBudgetDialog", () => {
  const REFUSAL = "That value is outside the allowed range.";
  function Host({ refusal }: { readonly refusal?: string }): JSX.Element {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Open it
        </button>
        <ChangeBudgetDialog
          open={open}
          account="Main"
          range={{ min: 60, max: 420 }}
          {...(refusal === undefined ? {} : { refusal })}
          onConfirm={() => setOpen(false)}
          onCancel={() => setOpen(false)}
        />
      </>
    );
  }
  const openIt = async (): Promise<{ trigger: HTMLElement; dialog: HTMLElement }> => {
    const trigger = screen.getByRole("button", { name: "Open it" });
    trigger.focus();
    fireEvent.click(trigger);
    return { trigger, dialog: await screen.findByRole("alertdialog") };
  };

  it("is an alertdialog, focus on Cancel, with the range, effect and marker", async () => {
    render(<Host />);
    const { dialog } = await openIt();
    expect(dialog).toHaveAccessibleName("Change budget");
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus(),
    );
    expect(within(dialog).getByText("Allowed: 60 to 420 requests per minute")).toBeInTheDocument();
    expect(within(dialog).getByText(COPY["W-63"])).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: SAVE_BUDGET })).toBeInTheDocument();
  });

  it("returns focus to its trigger on Cancel", async () => {
    render(<Host />);
    const { trigger, dialog } = await openIt();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("returns focus to its trigger on Confirm", async () => {
    render(<Host />);
    const { trigger, dialog } = await openIt();
    // The ui guard ignores a press inside its 400 ms window; move the monotonic clock past it, no sleep.
    const t0 = performance.now();
    vi.spyOn(performance, "now").mockReturnValue(t0 + 1000);
    fireEvent.click(within(dialog).getByRole("button", { name: SAVE_BUDGET }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("shows the server's refusal sentence and stays open", async () => {
    render(<Host refusal={REFUSAL} />);
    const { dialog } = await openIt();
    expect(within(dialog).getByText(REFUSAL)).toBeInTheDocument();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });
});

describe("the 1 Hz update announces nothing (SR-1)", () => {
  it("steps a meter per sample without a live region, a status or a shell line", () => {
    const rows = rateBudgetRows(SERVED_REPORT);
    const { container, rerender } = render(
      <>
        <ShellAnnouncer />
        <BudgetGrid rows={rows} />
      </>,
    );
    for (let used = 100; used < 105; used += 1) {
      rerender(
        <>
          <ShellAnnouncer />
          <BudgetGrid
            rows={rows.map((r) => ({ ...r, peakUsedPerMinute: used, utilisationPct: used / 6 }))}
          />
        </>,
      );
    }
    const meter = screen.getAllByRole("meter")[0];
    expect(meter).toHaveAttribute("aria-valuetext", expect.stringMatching(/requests per minute/));
    const grid = container.querySelector(".cv-connectivity__grid") as HTMLElement;
    // CMP-049 carries one pre-rendered, empty polite region of its own: a sample must leave it empty.
    for (const region of grid.querySelectorAll("[aria-live], [role=status], [role=alert]"))
      expect(region.textContent).toBe("");
    expect(live(container, "polite")).toBeEmptyDOMElement();
    expect(live(container, "assertive")).toBeEmptyDOMElement();
  });
});

// jsdom applies no forced-colors palette, so only the markup (word + glyph) and the stylesheet text are proved here;
// measured pass owed to PR-2 (Playwright).
describe("states are never colour alone (R2 forced colours)", () => {
  it("every state keeps its word and a glyph, whatever the palette", () => {
    for (const id of STATE_IDS) {
      const { container, unmount } = render(<StateTile id={id} label={`Tile ${id}`} />);
      expect(container.querySelector(".cv-health-tile__state, [aria-busy]")).not.toBeNull();
      if (id !== "S-13") {
        expect(container.querySelector(".cv-health-tile__glyph")).not.toBeNull();
        expect(container.textContent ?? "").not.toBe("");
      }
      unmount();
    }
  });

  it("the stylesheet gives the reserve band's edge and the active row system colours", () => {
    const css = readFileSync(
      resolve(import.meta.dirname, "../../../src/features/admin-connectivity/connectivity.css"),
      "utf8",
    );
    expect(css).toMatch(/@media \(forced-colors: active\)[\s\S]*CanvasText[\s\S]*Highlight/);
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/); // tokens, never literals
    expect(css).not.toMatch(/animation|transition/);
  });
});

// jsdom does no layout, so a 200 % reflow cannot be measured, only that values are text and no pixel width is fixed;
// measured pass owed to PR-2 (Playwright).
describe("R1: 200 % reflow (structure)", () => {
  it("keeps every value in the DOM as text and fixes no pixel width", () => {
    const { container } = render(<BudgetGrid rows={rateBudgetRows(SERVED_REPORT)} />);
    const text = container.textContent ?? "";
    for (const figure of [
      "600 requests per minute",
      "120 requests per minute",
      "510 requests per minute",
    ])
      expect(text).toContain(figure);
    expect(text).toContain("Not connected yet"); // Headroom: no figure, layout kept
    expect(container.innerHTML).not.toMatch(/width:\s*\d+(\.\d+)?px/);
    expect(container.innerHTML).not.toMatch(/overflow:\s*hidden/);
  });
});

describe("a figure the server does not serve", () => {
  it("reads Not connected yet, never 0, and draws no meter", () => {
    const rows = rateBudgetRows(SERVED_REPORT).map((r) => ({
      ...r,
      limitPerMinute: null,
      peakUsedPerMinute: null,
      utilisationPct: null,
    }));
    const { container } = render(<BudgetGrid rows={rows} />);
    expect(screen.queryAllByRole("meter")).toHaveLength(0);
    expect(container.textContent ?? "").toContain("Not connected yet");
    expect(container.textContent ?? "").not.toMatch(/\b0\b/);
    expect(container.textContent ?? "").not.toMatch(/In sync/);
  });

  it("never prints the served detail of a failed slice", () => {
    const { container } = render(
      <StateTile id="S-17" label="Rate budgets" lastGoodAt={Date.UTC(2026, 9, 22, 14, 1, 58)} />,
    );
    expect(container.textContent ?? "").not.toContain("probe failed");
    expect(container.textContent ?? "").toContain("last good 14:01:58");
  });
});

describe("accessible names (role queries)", () => {
  it("names each tile by its heading and its state in words", () => {
    render(<StateTile id="S-04" label="IP hold" />);
    const region = screen.getByRole("region", { name: /IP hold/ });
    expect(region).toHaveTextContent("On hold — all accounts");
  });
});
