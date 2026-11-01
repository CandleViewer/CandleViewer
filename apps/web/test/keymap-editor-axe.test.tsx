import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { beforeEach, describe, expect, it } from "vitest";
import { KeymapHost } from "../src/keymap/KeymapHost";
import { resetMeClaims, setMeClaims } from "../src/lib/auth/meCache";
import { buildRoutes } from "../src/routes/tree";
import { PreferencesProvider } from "../src/features/a11y-preferences/PreferencesContext";

/**
 * #305 (E10-S02) PR B, A11Y-305B-04: SCR-113's editor at R-202 through the real route tree, as the a11y gate opens it
 * (its h1 "Hotkeys", e2e/a11y/screens.ts), with axe over the editor in four states: the default, a refusal that offers
 * Swap, the acknowledgement, and Export with a failed import. jsdom has no layout, so contrast is the real-browser
 * collectors' (axe.collect.ts); none of these states changes a binding, so the tests share the keymap modules.
 */
// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

// Claims are set before render, as main.tsx runs the bootstrap before the router mounts.
beforeEach(() => {
  resetMeClaims();
  setMeClaims({ authenticated: true, role: "owner", permissions: [] });
});

/** R-202 in the shell, once its h1 has rendered; the editor's own section. */
async function openEditor(): Promise<HTMLElement> {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/settings/hotkeys"] });
  render(
    <PreferencesProvider>
      <KeymapHost />
      <RouterProvider router={router} />
    </PreferencesProvider>,
  );
  // the route tree's first render can pass the default 1 s under load: 5 s, as BackendUnreachable's
  const h1 = await screen.findByRole("heading", { level: 1, name: "Hotkeys" }, { timeout: 5_000 });
  await act(async () => {}); // flush the shell's mount effects
  return h1.closest("section") as HTMLElement;
}

async function serious(el: Element): Promise<string[]> {
  const res = await axe.run(el, { rules: { "color-contrast": { enabled: false } } });
  return res.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => v.id);
}

const inRow = (label: string) =>
  within(screen.getByText(label, { selector: 'th[scope="row"]' }).closest("tr") as HTMLElement);
function bind(label: string, key: string): void {
  const row = inRow(label);
  fireEvent.change(row.getByRole("textbox", { name: `Key for ${label}` }), {
    target: { value: key },
  });
  fireEvent.click(row.getByRole("button", { name: /^Save\b/ }));
}
const button = (name: string): HTMLElement => screen.getByText(name, { selector: "button" });

describe("A11Y-305B-04: the hotkey editor at R-202 has no serious or critical axe violation", () => {
  it("by default, with 'Hotkeys' as the page's one h1", { timeout: 30_000 }, async () => {
    const editor = await openEditor();
    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(await serious(editor)).toEqual([]);
  });

  it("with a refusal that offers Swap", { timeout: 30_000 }, async () => {
    const editor = await openEditor();
    bind("Price zoom in", "-");
    expect(inRow("Price zoom in").getByRole("button", { name: "Swap" })).toBeVisible();
    expect(await serious(editor)).toEqual([]);
  });

  it("with the acknowledgement offered", { timeout: 30_000 }, async () => {
    const editor = await openEditor();
    bind("Cancel all working orders for symbol", "Del");
    expect(button("I understand, bind anyway")).toBeVisible();
    expect(await serious(editor)).toEqual([]);
  });

  it("with a search, a context filter and a recording row", { timeout: 30_000 }, async () => {
    const editor = await openEditor();
    fireEvent.change(screen.getByLabelText("Search commands"), { target: { value: "zoom" } });
    fireEvent.change(screen.getByLabelText("Context"), { target: { value: "DOM" } });
    fireEvent.click(inRow("Price zoom in").getByRole("button", { name: /^Record\b/ }));
    expect(await serious(editor)).toEqual([]);
  });

  it("with the profile exported and an import that failed", { timeout: 30_000 }, async () => {
    const editor = await openEditor();
    fireEvent.click(button("Export"));
    fireEvent.change(screen.getByLabelText("Import keymap (JSON)"), { target: { value: "{" } });
    fireEvent.click(button("Import"));
    expect(screen.getByLabelText("Export keymap (JSON)")).toBeVisible();
    expect(within(editor).getByText("Import failed: not valid JSON")).toBeVisible();
    expect(await serious(editor)).toEqual([]);
  });
});
