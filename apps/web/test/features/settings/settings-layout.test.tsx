import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import {
  ResetPreview,
  SettingRow,
  SettingsLayout,
  currentSectionId,
  resultsSentence,
  searchSettings,
} from "../../../src/features/settings";
import { SEARCH_SAY_MS } from "../../../src/features/settings/useSettingsSearch";

/** Keys go to the focused element, as the browser does; no user-event dependency. */
const user = {
  click: (el: HTMLElement): void => {
    fireEvent.click(el);
  },
  keyboard: (keys: string): void => {
    for (const k of keys.match(/\{(\w+)\}/g) ?? []) {
      fireEvent.keyDown(document.activeElement ?? document.body, { key: k.slice(1, -1) });
    }
  },
};

/** jsdom has no layout; contrast is the real-browser a11y suite's. */
const NO_CONTRAST = { rules: { "color-contrast": { enabled: false } } };

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { id: string }[] }> };

function view(
  path = "/settings/appearance",
  reset?: Parameters<typeof SettingsLayout>[0]["reset"],
) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ShellAnnouncer />
      <SettingsLayout {...(reset ? { reset } : {})}>
        <h1>Appearance</h1>
      </SettingsLayout>
    </MemoryRouter>,
  );
}

afterEach(() => {
  clearAnnouncements();
  vi.useRealTimers();
});

describe("SettingsNav", () => {
  it("lists all nine sections in a Settings nav with aria-current on the open one", () => {
    view();
    const nav = screen.getByRole("navigation", { name: "Settings" });
    expect(within(nav).getAllByRole("listitem")).toHaveLength(9);
    expect(within(nav).getByRole("link", { name: "Appearance" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Hotkeys" })).not.toHaveAttribute("aria-current");
  });

  it("tells two sections of one route apart by their hash", () => {
    expect(currentSectionId("/settings/profile", "")).toBe("profile");
    expect(currentSectionId("/settings/profile", "#security")).toBe("security");
    expect(currentSectionId("/settings/appearance", "#accessibility")).toBe("accessibility");
    expect(currentSectionId("/settings/nothing", "")).toBeNull();
  });

  it("shows unbuilt sections disabled with a visible reason, focusable and never hidden", () => {
    view();
    const item = screen.getByRole("button", { name: "Trading defaults" });
    expect(item).toHaveAttribute("aria-disabled", "true");
    expect(item).toHaveAccessibleDescription(/not available yet/i);
    item.focus();
    expect(item).toHaveFocus();
  });

  it("moves between items with the arrow keys, Home and End", () => {
    view();
    const nav = screen.getByRole("navigation", { name: "Settings" });
    const links = [...nav.querySelectorAll<HTMLElement>("[data-nav-item]")];
    links[0]?.focus();
    user.keyboard("{ArrowDown}");
    expect(links[1]).toHaveFocus();
    user.keyboard("{End}");
    expect(links[links.length - 1]).toHaveFocus();
    user.keyboard("{ArrowDown}");
    expect(links[links.length - 1]).toHaveFocus();
    user.keyboard("{Home}{ArrowUp}");
    expect(links[0]).toHaveFocus();
  });
});

describe("settings search", () => {
  beforeEach(() => vi.useFakeTimers());

  it("announces the count once, after typing stops, with each section path", () => {
    view();
    const box = screen.getByRole("searchbox", { name: "Search settings" });
    fireEvent.change(box, { target: { value: "mo" } });
    fireEvent.change(box, { target: { value: "motion" } });
    const live = (): string => document.body.textContent ?? "";
    expect(live()).not.toMatch(/results?:/);
    act(() => {
      vi.advanceTimersByTime(SEARCH_SAY_MS);
    });
    expect(screen.getAllByText(/^2 results: /)).toHaveLength(1);
    expect(live()).toContain("Accessibility > Reduced motion");
  });

  it("lists each result with its path and scope, and says 0 results", () => {
    view();
    const box = screen.getByRole("searchbox", { name: "Search settings" });
    fireEvent.change(box, { target: { value: "palette" } });
    const results = screen.getByRole("region", { name: /search results/i });
    expect(within(results).getByText("Settings > Appearance > Chart palette")).toBeVisible();
    expect(within(results).getByText(/this device only/i)).toBeVisible();
    fireEvent.change(box, { target: { value: "zzzz" } });
    act(() => {
      vi.advanceTimersByTime(SEARCH_SAY_MS);
    });
    expect(screen.getByText("0 results.")).toBeInTheDocument();
  });

  it("finds an unbuilt section by name and states why it cannot be opened", () => {
    view();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search settings" }), {
      target: { value: "trading" },
    });
    const results = screen.getByRole("region", { name: /search results/i });
    expect(within(results).getByText("Settings > Trading defaults")).toBeVisible();
    expect(within(results).getByText(/not available yet/i)).toBeVisible();
    expect(within(results).queryByRole("link")).toBeNull();
  });

  it("pure helpers: singular, cap at five", () => {
    expect(resultsSentence(searchSettings("Reduced motion"))).toMatch(/^1 result: /);
    expect(resultsSentence(searchSettings("a"))).toMatch(/and \d+ more\.$/);
    expect(searchSettings("  ")).toEqual([]);
  });
});

describe("reset preview", () => {
  const items = [
    { id: "a", label: "Chart palette", current: "Colour-blind safe", defaultValue: "Default" },
    { id: "b", label: "Colour convention", current: "Standard", defaultValue: "Standard" },
  ];

  it("is disabled with a reason until the settings service exists", () => {
    view();
    const button = screen.getByRole("button", { name: /Reset Appearance/ });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(/not available yet/i);
  });

  it("previews only what would change, and Cancel changes nothing", () => {
    const onConfirm = vi.fn();
    view("/settings/appearance", { items, onConfirm });
    const trigger = screen.getByRole("button", { name: /Reset Appearance/ });
    user.click(trigger);
    expect(screen.getByRole("heading", { name: "Reset Appearance to defaults" })).toHaveFocus();
    expect(screen.getByText("Chart palette: Colour-blind safe to Default")).toBeVisible();
    expect(screen.queryByText(/Colour convention:/)).toBeNull();
    user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(trigger).toHaveFocus();
  });

  it("Esc cancels; confirm resets once and says how many", () => {
    const onConfirm = vi.fn();
    view("/settings/appearance", { items, onConfirm });
    user.click(screen.getByRole("button", { name: /Reset Appearance/ }));
    user.keyboard("{Escape}");
    expect(screen.queryByRole("heading", { name: /to defaults/ })).toBeNull();
    user.click(screen.getByRole("button", { name: /Reset Appearance/ }));
    user.click(screen.getByRole("button", { name: "Reset 1 setting" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Appearance reset: 1 settings restored.")).toBeInTheDocument();
  });

  it("with nothing to change the confirm is disabled with its reason", () => {
    render(
      <ResetPreview
        sectionLabel="Hotkeys"
        items={[items[1]!]}
        onConfirm={() => undefined}
        onCancel={() => undefined}
      />,
    );
    const confirm = screen.getByRole("button", { name: "Reset 0 settings" });
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(confirm).toHaveAccessibleDescription("Nothing would change.");
  });
});

describe("SettingRow", () => {
  it("names the control by its label and describes it with description and scope", () => {
    render(
      <SettingRow label="Reduced motion" description="Calm animation." scope="Applies to you.">
        {({ labelId, describedBy }) => (
          <input type="checkbox" aria-labelledby={labelId} aria-describedby={describedBy} />
        )}
      </SettingRow>,
    );
    const box = screen.getByRole("checkbox", { name: "Reduced motion" });
    expect(box).toHaveAccessibleDescription("Calm animation. Applies to you.");
  });
});

describe("axe", () => {
  it("has no violations in the layout, searching and previewing", async () => {
    const { container } = view("/settings/appearance", {
      items: [{ id: "a", label: "Chart palette", current: "x", defaultValue: "y" }],
      onConfirm: () => undefined,
    });
    expect((await axe.run(container, NO_CONTRAST)).violations).toEqual([]);
    user.click(screen.getByRole("button", { name: /Reset Appearance/ }));
    expect((await axe.run(container, NO_CONTRAST)).violations).toEqual([]);
    user.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search settings" }), {
      target: { value: "motion" },
    });
    expect((await axe.run(container, NO_CONTRAST)).violations).toEqual([]);
  });
});
