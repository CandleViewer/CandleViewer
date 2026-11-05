/**
 * E13-S01 (#423) S4: SCR-035 through the accessibility tree. The commit model (D06 §6), the T2 legs
 * (D06 §12; D05 T2-02, T2-06, T2-14; G-T2.1a–d, G-T2.3, G-T2.5), the keyboard and focus contract
 * (D06 §5.1–§5.2: K35-01..K35-11, FM-04, F-10) and axe on each state.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState, type JSX } from "react";
import { describe, expect, it } from "vitest";
import { SETTINGS } from "../../../src/features/indicators/copy";
import {
  normaliseDescriptor,
  type CatalogueEntry,
} from "../../../src/features/indicators/model/catalogue";
import {
  IndicatorSettingsDialog,
  settingsGate,
  type SettingsAccess,
} from "../../../src/features/indicators/settings/IndicatorSettingsDialog";
import { EMA } from "./fixtures";
import {
  bollEntry,
  charted,
  emaEntry,
  fakeClock,
  fakePreview,
  type Charted,
  type FakeClock,
  type FakePreview,
} from "./settingsHarness";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

async function serious(): Promise<string[]> {
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => v.id);
}

const WRITE: SettingsAccess = { viewAs: null, canWrite: true };

interface Opened {
  readonly chart: Charted;
  readonly clock: FakeClock;
  readonly preview: FakePreview;
  readonly opener: HTMLElement;
}

function open(
  which: "ema" | "boll",
  access: SettingsAccess = WRITE,
  entry?: CatalogueEntry,
): Opened {
  const chart = charted();
  const clock = fakeClock();
  const preview = fakePreview();
  function Host(): JSX.Element {
    const [shown, setShown] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setShown(true)}>
          Settings
        </button>
        <IndicatorSettingsDialog
          open={shown}
          onClose={() => setShown(false)}
          store={chart.store}
          chart="c"
          instanceId={chart[which]}
          entry={entry ?? (which === "ema" ? emaEntry : bollEntry)}
          label={which === "ema" ? "EMA 21" : "BB 20 2"}
          timeframe="5m"
          access={access}
          preview={preview}
          clock={clock}
        />
      </>
    );
  }
  render(<Host />);
  const opener = screen.getByRole("button", { name: "Settings" });
  opener.focus();
  fireEvent.click(opener);
  return { chart, clock, preview, opener };
}

const field = (name: string): HTMLElement => screen.getByRole("spinbutton", { name });
const type = (name: string, value: string): void => {
  fireEvent.change(field(name), { target: { value } });
};
const paramsOf = (o: Opened, which: "ema" | "boll") =>
  o.chart.store.selectInstances("c").find((i) => i.id === o.chart[which])?.params;
const liveText = (): string =>
  [...document.querySelectorAll("[aria-live]")].map((n) => n.textContent ?? "").join("|");

describe("SCR-035 opens and closes (FM-04, K35-09..K35-11)", () => {
  it("test_open_focuses_the_inputs_tab_and_names_the_dialog", () => {
    open("ema");
    const dialog = screen.getByRole("dialog", { name: "EMA 21 · price pane · 5m" });
    expect(document.activeElement).toBe(within(dialog).getByRole("tab", { name: "Inputs" }));
    expect(within(dialog).getByRole("tab", { name: "Inputs" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(within(dialog).queryByRole("tab", { name: "Alerts" })).not.toBeInTheDocument();
  });

  it("test_tab_order_follows_k35_with_close_after_apply_in_the_cycle", () => {
    open("boll");
    const dialog = screen.getByRole("dialog");
    const stops = [...dialog.querySelectorAll<HTMLElement>("button, input, [tabindex]")]
      // CMP-042 makes a panel a stop only when nothing in it is tabbable, which jsdom (no layout)
      // always reports; the browser sees the fields, so the panel is no stop there.
      .filter(
        (el) => el.tabIndex >= 0 && !["group", "tabpanel"].includes(el.getAttribute("role") ?? ""),
      )
      .map((el) => el.getAttribute("aria-label") ?? el.textContent ?? "");
    // CMP-043 puts Close first in the DOM; the trap cycles Apply → Close → the tabs (K35-11 last).
    expect(stops).toEqual([
      "Close BB 20 2 · price pane · 5m",
      "Inputs",
      "",
      "",
      SETTINGS.reset,
      SETTINGS.cancel,
      SETTINGS.apply,
    ]);
  });

  it("test_escape_cancels_reverts_and_returns_focus_to_the_opener", async () => {
    const o = open("boll");
    type("Period", "30");
    expect(o.preview.calls).toHaveLength(1);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await act(async () => {});
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(paramsOf(o, "boll")).toEqual({ n: 20, mult: 2 });
    expect(o.preview.cleared).toBe(1);
    expect(document.activeElement).toBe(o.opener);
  });

  it("test_cancel_button_reverts_like_escape", async () => {
    const o = open("boll");
    type("Period", "30");
    fireEvent.click(screen.getByRole("button", { name: SETTINGS.cancel }));
    await act(async () => {});
    expect(paramsOf(o, "boll")).toEqual({ n: 20, mult: 2 });
    expect(o.preview.cleared).toBe(1);
  });
});

describe("the commit model (D06 §6)", () => {
  it("test_server_instance_never_registers_on_a_keystroke_and_commits_on_enter", () => {
    const o = open("ema");
    expect(screen.getByText(SETTINGS.previewServer)).toBeInTheDocument();
    const before = o.chart.engine.calls.length;
    type("Period", "34");
    type("Period", "35");
    expect(o.chart.engine.calls).toHaveLength(before);
    expect(o.preview.calls).toHaveLength(0);
    fireEvent.keyDown(field("Period"), { key: "Enter" });
    expect(paramsOf(o, "ema")).toEqual({ n: 35 });
    expect(o.chart.engine.calls.at(-1)?.op).toBe("setParams");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("test_client_worker_previews_every_valid_change_without_debounce", () => {
    const o = open("boll");
    expect(screen.getByText(SETTINGS.previewWindow)).toBeInTheDocument();
    type("Period", "21");
    type("Period", "22");
    type("Period", "0");
    expect(o.preview.calls).toEqual([
      { n: 21, mult: 2 },
      { n: 22, mult: 2 },
    ]);
    expect(paramsOf(o, "boll")).toEqual({ n: 20, mult: 2 });
  });

  it("test_updating_shows_only_past_100ms_on_the_injected_clock", async () => {
    const o = open("boll");
    type("Period", "21");
    act(() => o.clock.advance(99));
    expect(liveText()).not.toContain(SETTINGS.updating);
    act(() => o.clock.advance(1));
    expect(liveText()).toContain(SETTINGS.updating);
    await act(() => o.preview.land());
    expect(liveText()).not.toContain(SETTINGS.updating);
    expect(o.clock.pending()).toBe(0);
  });

  it("test_a_preview_that_lands_in_time_never_shows_updating", async () => {
    const o = open("boll");
    type("Period", "21");
    await act(() => o.preview.land());
    act(() => o.clock.advance(500));
    expect(liveText()).not.toContain(SETTINGS.updating);
  });

  it("test_apply_commits_through_the_store_and_closes", async () => {
    const o = open("boll");
    type("Standard deviations", "2.5");
    fireEvent.click(screen.getByRole("button", { name: SETTINGS.apply }));
    await act(async () => {});
    expect(paramsOf(o, "boll")).toEqual({ n: 20, mult: 2.5 });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(o.opener);
  });

  it("test_a_server_refusal_keeps_the_dialog_open_with_the_deck_sentence", () => {
    const o = open("ema");
    o.chart.engine.capacity = 0;
    type("Period", "50");
    fireEvent.click(screen.getByRole("button", { name: SETTINGS.apply }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(liveText()).toContain(SETTINGS.atCapacity);
    expect(paramsOf(o, "ema")).toEqual({ n: 21 });
  });

  it("test_reset_restores_catalogue_defaults_and_clears_edited", () => {
    open("boll");
    type("Period", "30");
    expect(screen.getAllByText(SETTINGS.edited).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: SETTINGS.reset }));
    expect(field("Period")).toHaveValue("20");
    expect(screen.queryByText(SETTINGS.edited)).not.toBeInTheDocument();
  });
});

describe("validity is not T2 (T2-14, D11, F-10)", () => {
  it("test_invalid_value_is_refused_never_clamped", async () => {
    const o = open("boll");
    type("Standard deviations", "2.25");
    expect(field("Standard deviations")).toHaveValue("2.25");
    expect(screen.getByText("Standard deviations must be a multiple of 0.1.")).toBeInTheDocument();
    const apply = screen.getByRole("button", { name: SETTINGS.apply });
    expect(apply).toHaveAttribute("aria-disabled", "true");
    expect(apply).toHaveAccessibleDescription(SETTINGS.fixFirst);
    expect(within(apply).queryByRole("img", { name: "Not available" })).not.toBeInTheDocument();
    fireEvent.click(apply);
    expect(paramsOf(o, "boll")).toEqual({ n: 20, mult: 2 });
    expect(o.preview.calls).toHaveLength(0);
    expect(await serious()).toEqual([]);
  });

  it("test_enter_in_an_invalid_field_reannounces_and_commits_nothing", async () => {
    const o = open("boll");
    type("Period", "0");
    fireEvent.keyDown(field("Period"), { key: "Enter" });
    await act(async () => {});
    expect(liveText()).toContain("Period must be between 1 and 5000.");
    expect(paramsOf(o, "boll")).toEqual({ n: 20, mult: 2 });
  });

  it("test_apply_from_the_style_tab_focuses_the_first_invalid_field", async () => {
    open("boll");
    type("Period", "0");
    fireEvent.click(screen.getByRole("tab", { name: "Style" }));
    expect(screen.getByText(SETTINGS.stylePending)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: SETTINGS.apply }));
    expect(screen.getByRole("tab", { name: "Inputs" })).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(field("Period"));
    await act(async () => {});
    expect(liveText()).toContain(SETTINGS.fixFirst);
  });
});

describe("T2: the view-as leg first, one header notice (D06 §12; G-T2.1, G-T2.5)", () => {
  it("test_gate_checks_view_as_before_the_role", () => {
    expect(settingsGate({ viewAs: "alex", canWrite: false })?.sentence).toBe(
      "Read-only while viewing as alex.",
    );
    expect(settingsGate({ viewAs: null, canWrite: false })?.sentence).toBe(
      "Your role can't save workspaces.",
    );
    expect(settingsGate(WRITE)).toBeNull();
  });

  it.each([
    [{ viewAs: "alex", canWrite: true }, "Read-only while viewing as alex."],
    [{ viewAs: null, canWrite: false }, "Your role can't save workspaces."],
  ])("test_gated_apply_points_at_the_one_notice %#", async (access, sentence) => {
    const o = open("boll", access);
    expect(screen.getAllByText(sentence)).toHaveLength(1);
    const apply = screen.getByRole("button", { name: `Not available ${SETTINGS.apply}` });
    expect(apply).toHaveAttribute("aria-disabled", "true");
    expect(apply).not.toBeDisabled();
    expect(apply).toHaveAccessibleDescription(sentence);
    type("Period", "30");
    expect(o.preview.calls).toHaveLength(1);
    fireEvent.keyDown(field("Period"), { key: "Enter" });
    await act(async () => {});
    expect(liveText()).toContain(sentence);
    fireEvent.click(apply);
    await act(async () => {});
    expect(liveText()).toContain(sentence);
    expect(paramsOf(o, "boll")).toEqual({ n: 20, mult: 2 });
    expect(await serious()).toEqual([]);
  });
});

describe("a hostile catalogue schema (BQ-11)", () => {
  it("test_hostile_schema_is_one_safe_error_at_t0_on_the_injected_clock", async () => {
    const hostile = normaliseDescriptor({
      ...EMA,
      params_schema: { type: "object", properties: { n: { $ref: "#/x" } } },
    }) as CatalogueEntry;
    const o = open("ema", WRITE, hostile);
    expect(screen.getAllByText(SETTINGS.schemaRefused)).toHaveLength(1);
    expect(o.clock.now()).toBe(0);
    expect(o.clock.pending()).toBe(0);
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: SETTINGS.apply })).not.toBeInTheDocument();
    expect(await serious()).toEqual([]);
  });
});

describe("axe", () => {
  it("test_default_state_has_no_serious_violations", async () => {
    open("ema");
    expect(await serious()).toEqual([]);
  });
});
