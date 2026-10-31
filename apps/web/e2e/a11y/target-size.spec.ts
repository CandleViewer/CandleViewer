import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { json } from "../support/api";
import { openScreen } from "./open";
import { PR_IDS, REPORT_DIR, SCREENS, SIGNED_IN_SCREENS } from "./screens";
import {
  parseExceptionRegister,
  targetViolations,
  type TargetBox,
  type TargetException,
} from "./targetSize";

// E47-S05 (#1319), Gherkin "Targets meet the minimum or are registered exceptions" (WCAG 2.5.8): at
// compact density, the tighter of the two, every interactive control on every screen the a11y sweep
// opens is at least 24 x 24 CSS px or has 24 px of clear space, or a register row matches it.
// Writes reports/a11y/target-size.json as evidence; it is a report plus this assert, not a G-code.

const REGISTER = resolve(
  import.meta.dirname,
  "../../../../docs/qa/a11y/e47-target-size-exceptions.md",
);
const FRAME = { width: 1280, height: 800 };

const INTERACTIVE = [
  "a[href]",
  "button",
  "input:not([type=hidden])",
  "select",
  "textarea",
  "summary",
  '[role="button"]',
  '[role="link"]',
  '[role="tab"]',
  '[role="menuitem"]',
  '[role="checkbox"]',
  '[role="radio"]',
  '[role="switch"]',
  '[role="slider"]',
  '[role="combobox"]',
  '[tabindex]:not([tabindex="-1"])',
].join(",");

interface Measured extends TargetBox {
  readonly excepted: string | null;
}

/** Visible, enabled controls with their boxes; a registered exception tags its elements by selector. */
const measure = (page: Page, screen: string, register: readonly TargetException[]) =>
  page.evaluate(
    ({
      sel,
      rules,
    }): Array<
      Omit<TargetBox, "exempt"> & { exempt?: "inline" | "user-agent"; excepted: string | null }
    > => {
      const out: Array<
        Omit<TargetBox, "exempt"> & { exempt?: "inline" | "user-agent"; excepted: string | null }
      > = [];
      for (const el of document.querySelectorAll<HTMLElement>(sel)) {
        const cs = getComputedStyle(el);
        if (cs.visibility === "hidden" || cs.display === "none") continue;
        if ((el as HTMLButtonElement).disabled === true) continue; // inactive controls are exempt
        if (el.closest("[inert]") !== null) continue;
        // A native checkbox or radio is hit through its label too: the target is their union (an inline
        // label's own box is a line tall, shorter than the control it wraps).
        const native =
          el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio");
        const own = el.getBoundingClientRect();
        const lab = native ? (el.labels?.[0] ?? null) : null;
        const lr = lab?.getBoundingClientRect();
        const box =
          lr === undefined
            ? own
            : new DOMRect(
                Math.min(own.x, lr.x),
                Math.min(own.y, lr.y),
                Math.max(own.right, lr.right) - Math.min(own.x, lr.x),
                Math.max(own.bottom, lr.bottom) - Math.min(own.y, lr.y),
              );
        // Zero-size or a 1 px clip: visually hidden until focus (the skip link), not a pointer target.
        if (box.width <= 1 || box.height <= 1) continue;
        // Inline: a link in a run of text, not a block or a flex item of its own.
        const inline =
          el.tagName === "A" &&
          cs.display === "inline" &&
          (el.parentElement?.textContent ?? "").trim() !== (el.textContent ?? "").trim();
        const hit = rules.find(
          (r) =>
            (r.screen === "*" || r.screen === screen) &&
            r.selector !== "" &&
            el.matches(r.selector),
        );
        const id = `${el.tagName.toLowerCase()}${el.id === "" ? "" : `#${el.id}`}[${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 30)}]`;
        out.push({
          id,
          x: box.x,
          y: box.y,
          w: box.width,
          h: box.height,
          ...(inline ? { exempt: "inline" as const } : {}),
          excepted: hit?.id ?? null,
        });
      }
      return out;
    },
    {
      sel: INTERACTIVE,
      rules: register.map((r) => ({ id: r.id, screen: r.screen, selector: r.selector })),
    },
  ) as Promise<Measured[]>;

test("every control is 24 px or has 24 px of space, or is a registered exception (compact)", async ({
  page,
}) => {
  const register = parseExceptionRegister(readFileSync(REGISTER, "utf8"));
  await page.setViewportSize(FRAME);
  const report: Record<string, unknown> = {};
  const failures: string[] = [];
  const screens = [...SCREENS, ...SIGNED_IN_SCREENS].filter((s) => PR_IDS.has(s.id) || s.signedIn);
  for (const s of screens) {
    await openScreen(page, s);
    await page.route("**/api/v1/me/preferences", (r) =>
      r.fulfill(json({ appearance: { density: "compact" } })),
    );
    await page.reload();
    await expect(page.getByRole("main").first()).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
    const boxes = await measure(page, s.id, register);
    const bad = targetViolations(boxes);
    const open = bad.filter((v) => boxes.find((b) => b.id === v.id)?.excepted == null);
    const smallest = boxes.reduce<Measured | null>(
      (m, b) => (m === null || Math.min(b.w, b.h) < Math.min(m.w, m.h) ? b : m),
      null,
    );
    report[s.id] = {
      targets: boxes.length,
      underMinimum: boxes
        .filter((b) => Math.min(b.w, b.h) < 24)
        .map((b) => `${b.id} ${b.w.toFixed(0)}x${b.h.toFixed(0)}`),
      smallest: smallest === null ? null : { id: smallest.id, w: smallest.w, h: smallest.h },
      violations: bad,
      unregistered: open,
    };
    for (const v of open)
      failures.push(
        `${s.id}: ${v.id} is ${v.w.toFixed(1)}x${v.h.toFixed(1)}, crowded by ${v.crowdedBy}`,
      );
  }
  mkdirSync(REPORT_DIR, { recursive: true });
  writeFileSync(`${REPORT_DIR}/target-size.json`, `${JSON.stringify(report, null, 2)}\n`);
  expect(failures, "unregistered targets under 24 px").toEqual([]);
});

test("the register names an alternative for every exception", () => {
  const register = parseExceptionRegister(readFileSync(REGISTER, "utf8"));
  for (const r of register) expect(r.alternative, `${r.id} has no alternative`).not.toBe("");
});
