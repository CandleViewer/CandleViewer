// E05-Q02 (#262) automatable manual passes on the built Storybook, in the e05-q02-ds.qa.ts style (same
// loopback server, same Playwright from apps/web, no new dependency). Three groups; each check writes one
// record, the run fails if any record is a failure:
//   keyboard  - real key events (page.keyboard, not userEvent) through the documented interactions: skip link,
//               combobox, menu, table (sort, grid arrows, Home / End, Ctrl+Home / Ctrl+End, row select),
//               ConfirmDialog standard and hold (the hold's discrete two-press path runs in the story's own
//               play function on the story clock; the check below asserts that play finished and that the
//               hold Confirm never reads a bare Enter), plus a generic Tab walk over every story
//               (a fixed-point trap, or a repeated focus cycle shorter than the tabbable count outside an
//               aria-modal, fails unless Escape takes focus out of the open dialog; reach is recorded per
//               element, SC 2.1.1 / 2.1.2). Keyboard, Tab walk, zoom and motion run in all three themes at
//               compact density; a story that pins its own motion is recorded with skip: true.
//   zoom      - a dense table (compact density, the three themes) at 200 % zoom (a 640 x 400 CSS-px viewport,
//               full-page-zoom emulation, WCAG 1.4.4; SC 1.4.10 reflow at 320 x 256 is not run here) and
//               125 % text scale (root font-size 125 %, WCAG 1.4.4): no horizontal page
//               scroll, no clipped text without a full-text twin, no data loss (every header and cell text of
//               the 1280 px render is present).
//   motion    - every story under data-motion="reduce" against the motion-safe render: each element whose
//               animation the motion-safe render runs and the reduced render does not still shows its end
//               state (visible, with text or an accessible name), SC 2.3.3 / 1.3.1 / 4.1.3.
// Run (after storybook:build), from apps/web:
//   A11Y_SHA=$(git rev-parse HEAD) A11Y_OUT=<dir> npx playwright test -c ../../docs/plan/a11y/_tools/e05-q02-manual.config.ts
// Writes <A11Y_OUT>/manual/<check>.json. A11Y_ONLY filters motion-probe stories (substrings).
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const OUT = join(process.env["A11Y_OUT"] ?? join(tmpdir(), "e05-q02-ds"), "manual");
const THEMES = ["dark", "light", "high-contrast"] as const;
const STORY_TIMEOUT_MS = 20_000;

interface Rec {
  readonly check: string;
  readonly group: string;
  readonly story: string;
  readonly theme: string;
  readonly sc: string;
  readonly pass: boolean;
  /** Not applicable: recorded, never counted as asserted. */
  readonly skip?: boolean;
  readonly detail: string;
}
const isRecord = (v: unknown): v is { [k: string]: unknown } =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const url = (story: string, theme: string, density: string, motion = "system"): string =>
  `/iframe.html?id=${story}&viewMode=story&globals=theme:${theme};density:${density};motion:${motion};a11y.manual:!true`;

const pinnedFinished = (): boolean => {
  const preview = (window as unknown as { __STORYBOOK_PREVIEW__?: { currentRender?: unknown } })
    .__STORYBOOK_PREVIEW__;
  const render = preview?.currentRender as { phase?: string } | undefined;
  return render?.phase === "finished";
};

/** The theme the running test drives; each test sets it first (one test per worker at a time). */
let THEME: string = "dark";

async function open(
  page: Page,
  story: string,
  theme = THEME,
  density = "compact",
  motion = "system",
): Promise<void> {
  await page.goto(url(story, theme, density, motion), { timeout: STORY_TIMEOUT_MS });
  await page.waitForFunction(pinnedFinished, undefined, {
    polling: 50,
    timeout: STORY_TIMEOUT_MS,
  });
  // A play function leaves focus where it ended (the menu's trigger, say) and Chromium starts the next Tab
  // from there: put the sequential-focus start back at the top of the document.
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    document.body.tabIndex = -1;
    document.body.focus();
    document.body.removeAttribute("tabindex");
    getSelection()?.removeAllRanges();
  });
}

const records: Rec[] = [];
const save = (name: string, rows: readonly Rec[]): void => {
  mkdirSync(OUT, { recursive: true });
  writeFileSync(join(OUT, `${name}.json`), JSON.stringify(rows, null, 2));
  records.push(...rows);
};
const rec = (
  check: string,
  group: string,
  story: string,
  sc: string,
  pass: boolean,
  detail: string,
  theme = THEME,
  skip = false,
): Rec => ({ check, group, story, theme, sc, pass, ...(skip ? { skip } : {}), detail });
const failures = (rows: readonly Rec[]): string =>
  rows
    .filter((r) => !r.pass)
    .map((r) => `${r.check} [${r.story}/${r.theme}]: ${r.detail}`)
    .join("\n");

test.beforeAll(() => {
  if (process.env["A11Y_KEEP"] !== "1") rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });
});

// --------------------------------------------------------------------------------------------- keyboard

const focusLabel = (page: Page): Promise<string> =>
  page.evaluate(() => {
    const el = document.activeElement;
    if (el === null || el === document.body) return "(body)";
    const own = el.getAttribute("aria-label") ?? el.textContent ?? "";
    return `${el.tagName.toLowerCase()}[${el.getAttribute("role") ?? ""}] ${own.trim().slice(0, 40)}`;
  });

/** The grid position of the focused cell: [aria-rowindex or row ordinal, cell ordinal]. */
const gridPos = (page: Page): Promise<string> =>
  page.evaluate(() => {
    const el = document.activeElement?.closest("td,th");
    const row = el?.closest("tr");
    if (!el || !row) return "none";
    const rows = [...(row.closest("table")?.querySelectorAll("tr") ?? [])];
    return `${rows.indexOf(row)},${[...row.children].indexOf(el)}`;
  });

for (const theme of THEMES)
  test(`keyboard: skip link, ${theme}`, async ({ page }) => {
    THEME = theme;
    const rows: Rec[] = [];
    await open(page, "atoms-skiplink--unfocused");
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.keyboard.press("Tab");
    const first = await focusLabel(page);
    rows.push(
      rec(
        "skip link is the first Tab stop",
        "keyboard",
        "atoms-skiplink--unfocused",
        "2.4.1",
        /Skip to main content/.test(first),
        first,
      ),
    );
    await page.keyboard.press("Enter");
    const target = await page.evaluate(() => ({
      role: document.activeElement?.getAttribute("role") ?? document.activeElement?.tagName,
      tag: document.activeElement?.tagName,
    }));
    rows.push(
      rec(
        "Enter moves focus to the main region",
        "keyboard",
        "atoms-skiplink--unfocused",
        "2.4.1",
        target.tag === "MAIN" || target.role === "main",
        JSON.stringify(target),
      ),
    );
    save(`keyboard-skiplink-${theme}`, rows);
    expect(failures(rows)).toBe("");
  });

for (const theme of THEMES)
  test(`keyboard: combobox, ${theme}`, async ({ page }) => {
    THEME = theme;
    const rows: Rec[] = [];
    const story = "molecules-combobox--sync";
    await open(page, story);
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => document.activeElement?.getAttribute("role"));
    rows.push(
      rec(
        "Tab reaches the combobox",
        "keyboard",
        story,
        "2.1.1",
        focused === "combobox",
        String(focused),
      ),
    );
    await page.keyboard.press("ArrowDown");
    const expanded = await page.getByRole("combobox").getAttribute("aria-expanded");
    rows.push(
      rec(
        "ArrowDown opens the list",
        "keyboard",
        story,
        "2.1.1",
        expanded === "true",
        `aria-expanded=${String(expanded)}`,
      ),
    );
    const options = await page.getByRole("option").count();
    rows.push(
      rec(
        "the open list exposes options",
        "keyboard",
        story,
        "1.3.1",
        options > 0,
        `${options} option(s)`,
      ),
    );
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    const value = await page.getByRole("combobox").inputValue();
    const closed = await page.getByRole("combobox").getAttribute("aria-expanded");
    rows.push(
      rec(
        "ArrowDown then Enter picks an option and closes",
        "keyboard",
        story,
        "2.1.1",
        value !== "" && closed === "false",
        `value="${value}", aria-expanded=${String(closed)}`,
      ),
    );
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Escape");
    const afterEsc = await page.getByRole("combobox").getAttribute("aria-expanded");
    rows.push(
      rec(
        "Escape closes the list; focus stays in the field",
        "keyboard",
        story,
        "2.1.1",
        afterEsc === "false" && (await focusLabel(page)).includes("combobox"),
        `aria-expanded=${String(afterEsc)}`,
      ),
    );
    save(`keyboard-combobox-${theme}`, rows);
    expect(failures(rows)).toBe("");
  });

for (const theme of THEMES)
  test(`keyboard: menu, ${theme}`, async ({ page }) => {
    THEME = theme;
    const rows: Rec[] = [];
    const story = "molecules-menu--default";
    await open(page, story);
    await page.keyboard.press("Tab");
    const trigger = page.getByRole("button", { name: "Layer actions" });
    rows.push(
      rec(
        "Tab reaches the trigger",
        "keyboard",
        story,
        "2.1.1",
        await trigger.evaluate((e) => e === document.activeElement),
        await focusLabel(page),
      ),
    );
    await page.keyboard.press("Enter");
    const menu = await page.getByRole("menu").count();
    const first = await focusLabel(page);
    rows.push(
      rec(
        "Enter opens the menu, focus on the first item",
        "keyboard",
        story,
        "2.1.1",
        menu === 1 && /menuitem/.test(first),
        first,
      ),
    );
    await page.keyboard.press("ArrowDown");
    const second = await focusLabel(page);
    rows.push(
      rec(
        "ArrowDown moves to the next item",
        "keyboard",
        story,
        "2.1.1",
        second !== first && /menuitem/.test(second),
        second,
      ),
    );
    await page.keyboard.press("End");
    const last = await focusLabel(page);
    rows.push(
      rec("End moves to the last item", "keyboard", story, "2.1.1", /Remove/.test(last), last),
    );
    await page.keyboard.press("Escape");
    await page
      .getByRole("menu")
      .waitFor({ state: "detached", timeout: 2000 })
      .catch(() => undefined);
    rows.push(
      rec(
        "Escape closes the menu and returns focus to the trigger",
        "keyboard",
        story,
        "2.4.3",
        (await page.getByRole("menu").count()) === 0 &&
          (await trigger.evaluate((e) => e === document.activeElement)),
        await focusLabel(page),
      ),
    );
    await page.keyboard.press("Enter");
    await page.getByRole("menu").waitFor({ timeout: 5_000 });
    await page.keyboard.press("Enter");
    await page
      .getByRole("menu")
      .waitFor({ state: "detached", timeout: 2000 })
      .catch(() => undefined);
    rows.push(
      rec(
        "Enter on an item activates it and closes the menu",
        "keyboard",
        story,
        "2.1.1",
        (await page.getByRole("menu").count()) === 0 &&
          (await trigger.evaluate((e) => e === document.activeElement)),
        await focusLabel(page),
      ),
    );
    save(`keyboard-menu-${theme}`, rows);
    expect(failures(rows)).toBe("");
  });

for (const theme of THEMES)
  test(`keyboard: table, ${theme}`, async ({ page }) => {
    THEME = theme;
    const rows: Rec[] = [];
    const story = "molecules-table--grid";
    await open(page, story);
    await page.keyboard.press("Tab");
    rows.push(
      rec(
        "Tab enters the grid on the first header",
        "keyboard",
        story,
        "2.1.1",
        (await gridPos(page)) === "0,0",
        await gridPos(page),
      ),
    );
    const move = async (
      keys: string,
      expected: (p: string) => boolean,
      name: string,
    ): Promise<void> => {
      await page.keyboard.press(keys);
      const p = await gridPos(page);
      rows.push(rec(`${keys}: ${name}`, "keyboard", story, "2.1.1", expected(p), p));
    };
    await move("ArrowDown", (p) => p === "1,0", "next row, same column");
    await move("ArrowRight", (p) => p === "1,1", "next cell");
    await move("End", (p) => p.startsWith("1,") && p !== "1,1", "last cell of the row");
    await move("Home", (p) => p === "1,0", "first cell of the row");
    await move(
      "Control+End",
      (p) => {
        const [r, c] = p.split(",").map(Number);
        return (r ?? 0) > 1 && (c ?? 0) > 1;
      },
      "last cell of the grid",
    );
    await move("Control+Home", (p) => p === "0,0", "first cell of the grid");
    await page.keyboard.press("Tab");
    const out = await page.evaluate(
      () => !document.querySelector("table")?.contains(document.activeElement),
    );
    rows.push(
      rec(
        "Tab leaves the grid (one tab stop)",
        "keyboard",
        story,
        "2.1.2",
        out,
        await focusLabel(page),
      ),
    );

    const sortable = "molecules-table--sortable";
    await open(page, sortable);
    await page.keyboard.press("Tab");
    const header = page.locator("th", { has: page.locator("button", { hasText: "Symbol" }) });
    const before = await header.getAttribute("aria-sort");
    await page.keyboard.press("Enter");
    const after = await header.getAttribute("aria-sort");
    rows.push(
      rec(
        "Enter on a sortable header changes aria-sort",
        "keyboard",
        sortable,
        "2.1.1",
        before !== after && after !== "none",
        `${String(before)} -> ${String(after)}`,
      ),
    );

    const selectable = "molecules-table--selectable";
    await open(page, selectable);
    await page.keyboard.press("Tab");
    // The story ends with every row selected, so Space on select-all clears them.
    const checked = (): Promise<number> => page.getByRole("checkbox", { checked: true }).count();
    const was = await checked();
    await page.keyboard.press("Space");
    // A failed wait is recorded by the row below (now !== 0), not thrown.
    await expect
      .poll(checked, { timeout: 5_000 })
      .toBe(0)
      .catch(() => undefined);
    const now = await checked();
    rows.push(
      rec(
        "Space on select-all toggles every row",
        "keyboard",
        selectable,
        "2.1.1",
        was > 1 && now === 0,
        `${was} checked -> ${now} checked`,
      ),
    );
    await page.keyboard.press("Space");
    await expect
      .poll(checked, { timeout: 5_000 })
      .toBe(was)
      .catch(() => undefined);
    rows.push(
      rec(
        "Space again selects them all",
        "keyboard",
        selectable,
        "2.1.1",
        (await checked()) === was,
        `${await checked()} checked`,
      ),
    );
    save(`keyboard-table-${theme}`, rows);
    expect(failures(rows)).toBe("");
  });

for (const theme of THEMES)
  test(`keyboard: confirm dialog, ${theme}`, async ({ page }) => {
    THEME = theme;
    const rows: Rec[] = [];
    const std = "molecules-confirmdialog--standard";
    await open(page, std);
    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter");
    await page.getByRole("alertdialog").waitFor();
    rows.push(
      rec(
        "Enter on the opener opens the dialog, focus on Cancel",
        "keyboard",
        std,
        "2.4.3",
        /Cancel/.test(await focusLabel(page)),
        await focusLabel(page),
      ),
    );
    await page.keyboard.press("Tab");
    rows.push(
      rec(
        "Tab reaches Confirm",
        "keyboard",
        std,
        "2.1.1",
        /Freeze sub_001/.test(await focusLabel(page)),
        await focusLabel(page),
      ),
    );
    await page.keyboard.press("Tab");
    rows.push(
      rec(
        "focus stays inside the dialog (no trap exit, no escape to the page)",
        "keyboard",
        std,
        "2.1.2",
        await page.evaluate(() => document.activeElement?.closest("[role=alertdialog]") !== null),
        await focusLabel(page),
      ),
    );
    await page.keyboard.press("Escape");
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    rows.push(
      rec(
        "Escape closes the dialog, focus returns to the opener",
        "keyboard",
        std,
        "2.4.3",
        /Freeze sub_001/.test(await focusLabel(page)),
        await focusLabel(page),
      ),
    );

    // The hold: the story's play function runs the whole path (pointer hold, early release, the discrete
    // double press with real key events) on the story clock; a story the play function failed never reaches
    // phase "finished", so open() passing is the assertion. Here: the hold Confirm does not read a bare Enter.
    for (const hold of [
      "molecules-confirmdialog--hold",
      "molecules-confirmdialog--hold-keyboard",
      "molecules-confirmdialog--hold-released-early",
    ]) {
      await open(page, hold);
      rows.push(
        rec(
          "the hold story's play function (keyboard and pointer paths) completes",
          "keyboard",
          hold,
          "2.1.1",
          true,
          "phase finished",
        ),
      );
    }
    const held = "molecules-confirmdialog--hold";
    await open(page, held);
    await page.getByRole("button", { name: "Flatten all" }).focus();
    await page.keyboard.press("Enter");
    await page.getByRole("alertdialog").waitFor();
    const confirm = page.getByRole("button", { name: /flatten 4 positions — all accounts/i });
    await confirm.focus();
    await page.keyboard.press("Enter");
    rows.push(
      rec(
        "a bare Enter on the hold Confirm does not confirm",
        "keyboard",
        held,
        "2.1.1",
        (await page.getByRole("alertdialog").count()) === 1,
        "dialog still open",
      ),
    );
    rows.push(
      rec(
        "the hold ring has a name and a text twin",
        "keyboard",
        held,
        "1.3.1",
        (await page.getByRole("progressbar").count()) === 1 &&
          /Hold to/.test(
            (await page.getByRole("progressbar").getAttribute("aria-label")) ??
              (await page.getByRole("progressbar").getAttribute("aria-labelledby")) ??
              "",
          ),
        "progressbar present",
      ),
    );
    save(`keyboard-confirm-${theme}`, rows);
    expect(failures(rows)).toBe("");
  });

// Generic Tab walk over every story: every tabbable element is reached; Tab never gets stuck.
const STATIC =
  process.env["A11Y_STATIC"] ?? resolve(process.cwd(), "../../packages/ui/storybook-static");
function storyIds(): string[] {
  const body: unknown = JSON.parse(readFileSync(join(STATIC, "index.json"), "utf8"));
  const entries = isRecord(body) && isRecord(body["entries"]) ? body["entries"] : {};
  const only = (process.env["A11Y_ONLY"] ?? "").split(",").filter((x) => x !== "");
  const ids: string[] = [];
  for (const [id, e] of Object.entries(entries)) {
    if (!isRecord(e) || e["type"] !== "story") continue;
    const tags = Array.isArray(e["tags"]) ? e["tags"] : [];
    if (tags.includes("perf")) continue;
    if (only.length === 0 || only.some((o) => id.includes(o))) ids.push(id);
  }
  return ids.sort();
}
const IDS = storyIds();
const CHUNK = Math.ceil(IDS.length / 16);

interface Walk {
  readonly count: number;
  readonly modal: boolean;
  readonly reached: number;
  /** Length of a repeated focus cycle entered before the document end (1 = focus never moves); 0 = none. */
  readonly cycle: number;
  readonly unreachedGrouped: number;
  readonly unreachedOther: readonly string[];
}

/**
 * Press Tab through the open story, from the top, until focus leaves the document (the "(body)" stop) or
 * count + 3 presses. Detects: a fixed point (focus does not move) and any repeated focus cycle entered before
 * the document end that is shorter than the tabbable count while no aria-modal is present (a modal's own
 * focus trap legitimately cycles). Records reach: every tabbable element is tagged, and those never focused
 * are counted as grouped (a radio group takes one Tab stop, the rest are arrow-key members) or listed.
 */
async function walk(page: Page): Promise<Walk> {
  const res = await page.evaluate(() => {
    const sel = "a[href],button,input,select,textarea,summary,[tabindex],[contenteditable='true']";
    const vis = (el: Element): boolean => {
      const s = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return s.visibility !== "hidden" && s.display !== "none" && (r.width > 0 || r.height > 0);
    };
    const tabbable = (el: Element): boolean =>
      vis(el) &&
      (el as HTMLElement).tabIndex >= 0 &&
      !(el as HTMLButtonElement).disabled &&
      el.closest("[inert],[hidden]") === null &&
      el.closest("[aria-hidden='true']") === null;
    const all = [...document.querySelectorAll(sel)].filter(tabbable);
    const grouped: boolean[] = [];
    const named: string[] = [];
    all.forEach((el, i) => {
      el.setAttribute("data-q02-tab", String(i));
      grouped.push(el instanceof HTMLInputElement && el.type === "radio");
      named.push(
        `${el.tagName.toLowerCase()}.${String(el.getAttribute("class") ?? "").split(" ")[0] ?? ""} "${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 24)}"`,
      );
    });
    const modal = document.querySelector("[aria-modal='true']") !== null;
    return { count: all.length, modal, grouped, named };
  });
  const seq: string[] = [];
  let cycle = 0;
  for (let n = 0; n < res.count + 3; n += 1) {
    await page.keyboard.press("Tab");
    const key = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return "(body)";
      const tag = el.getAttribute("data-q02-tab");
      if (tag !== null) return tag;
      const path: string[] = [];
      for (let e: Element | null = el; e && path.length < 6; e = e.parentElement)
        path.push(
          `${e.tagName}${e.id}${String([...(e.parentElement?.children ?? [])].indexOf(e))}`,
        );
      return `x:${path.join("<")}`;
    });
    if (key === "(body)") break; // focus left the document: the end of the document order
    const first = seq.indexOf(key);
    if (first >= 0) {
      cycle = seq.length - first;
      break;
    }
    seq.push(key);
  }
  const reachedSet = new Set(seq);
  let unreachedGrouped = 0;
  const unreachedOther: string[] = [];
  for (let i = 0; i < res.count; i += 1) {
    if (reachedSet.has(String(i))) continue;
    if (res.grouped[i] === true) unreachedGrouped += 1;
    else unreachedOther.push(res.named[i] ?? String(i));
  }
  return {
    count: res.count,
    modal: res.modal,
    reached: reachedSet.size,
    cycle: res.modal ? 0 : cycle > 0 && cycle < res.count ? cycle : 0,
    unreachedGrouped,
    unreachedOther,
  };
}

/**
 * With focus on the first tabbable stop inside an open dialog, does Escape take focus out of it (the dialog
 * closes, or asks its host to and returns focus to its opener)? A demo story may pin `open`, so the dialog
 * node can stay; the exit is the focus leaving it. Two presses at most: the first may dismiss a tooltip.
 */
async function escapeLeaves(page: Page): Promise<boolean> {
  const had = await page.evaluate(() => {
    const dialog = document.querySelector("[role='dialog']");
    const inner = dialog?.querySelector<HTMLElement>("[data-q02-tab]");
    inner?.focus();
    return inner !== undefined && inner !== null;
  });
  if (!had) return false;
  const out = (): Promise<boolean> =>
    page.evaluate(() => {
      const dialog = document.querySelector("[role='dialog']");
      return dialog === null || !dialog.contains(document.activeElement);
    });
  // The first Escape dismisses the focused control's tooltip (SC 1.4.13), the second leaves the dialog.
  for (let n = 0; n < 2; n += 1) {
    await page.keyboard.press("Escape");
    const left = await expect
      .poll(out, { timeout: 1_500 })
      .toBe(true)
      .then(() => true)
      .catch(() => false);
    if (left) return true;
  }
  return false;
}

for (const theme of THEMES) {
  for (let i = 0; i < IDS.length; i += CHUNK) {
    const chunk = IDS.slice(i, i + CHUNK);
    test(`tab walk ${String(i / CHUNK + 1)}, ${theme}`, async ({ page }) => {
      test.setTimeout(900_000);
      THEME = theme;
      const rows: Rec[] = [];
      for (const story of chunk) {
        await open(page, story);
        let w = await walk(page);
        const cycled = w.cycle;
        // Pass: no focus cycle shorter than the tabbable count (outside a modal), and the first Tab lands on
        // a stop when something is tabbable. Unreached elements are recorded in the detail, not asserted.
        // A cycle through an open non-modal dialog (drawer, popover) is a standard-exit case, not a trap,
        // when Escape takes focus out of that dialog (SC 2.1.2 allows any standard exit): it is passed with that note.
        let exit = "";
        if (w.cycle > 0) {
          const closed = await escapeLeaves(page);
          exit = closed
            ? " cycleExit=Escape takes focus out of the open non-modal dialog"
            : " cycleExit=none";
          if (closed) w = { ...w, cycle: 0 };
        }
        const pass = w.cycle === 0 && (w.count === 0 || w.reached > 0);
        rows.push(
          rec(
            "Tab walk: no trap or short focus cycle, the first Tab reaches a stop",
            "keyboard",
            story,
            "2.1.1 / 2.1.2",
            pass,
            `tabbable=${w.count} reached=${w.reached} cycle=${cycled} modal=${String(w.modal)} unreachedGrouped=${w.unreachedGrouped} unreachedOther=${w.unreachedOther.length}${exit}${w.unreachedOther.length > 0 ? ` [${w.unreachedOther.slice(0, 4).join("; ")}]` : ""}`,
          ),
        );
      }
      save(`tabwalk-${theme}-${String(i / CHUNK + 1).padStart(2, "0")}`, rows);
      expect(failures(rows)).toBe("");
    });
  }
}

test("negative controls: the keyboard trap, cycle and clip checks trip", async ({ page }) => {
  const trapStory = "molecules-table--compact";
  const rows: Rec[] = [];
  // 1. A fixed point: Tab always lands on the same button.
  await open(page, trapStory);
  await page.evaluate(() => {
    const root = document.querySelector("#storybook-root") ?? document.body;
    root.insertAdjacentHTML(
      "beforeend",
      '<button id="t1">a</button><button id="t2">b</button><button id="t3">c</button><div id="clip" style="width:20px;overflow:hidden;white-space:nowrap">a long clipped sentence</div>',
    );
    document.addEventListener("keydown", (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        document.getElementById("t1")?.focus();
      }
    });
  });
  const fixed = await walk(page);
  rows.push(
    rec(
      "controls trip: a fixed-point Tab trap is detected",
      "control",
      trapStory,
      "2.1.2",
      fixed.cycle === 1,
      JSON.stringify(fixed),
    ),
  );
  const cut = await clipped(page);
  rows.push(
    rec(
      "controls trip: a hard clip is detected",
      "control",
      trapStory,
      "1.4.4 (200 % zoom)",
      cut.hard.some((h) => h.includes("long clipped")),
      cut.hard.join("; "),
    ),
  );
  // 2. A two-element cycle among three-plus stops: Tab alternates t1 and t2 and never reaches the rest.
  await open(page, trapStory);
  await page.evaluate(() => {
    const root = document.querySelector("#storybook-root") ?? document.body;
    root.insertAdjacentHTML(
      "beforeend",
      '<button id="t1">a</button><button id="t2">b</button><button id="t3">c</button>',
    );
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Tab") return;
      e.preventDefault();
      const on = document.activeElement?.id;
      document.getElementById(on === "t1" ? "t2" : "t1")?.focus();
    });
  });
  const loop = await walk(page);
  rows.push(
    rec(
      "controls trip: a short focus cycle is detected",
      "control",
      trapStory,
      "2.1.2",
      loop.cycle === 2,
      JSON.stringify(loop),
    ),
  );
  // 3. A modal's own cycle is not flagged.
  await open(page, trapStory);
  await page.evaluate(() => {
    const root = document.querySelector("#storybook-root") ?? document.body;
    root.insertAdjacentHTML(
      "beforeend",
      '<div aria-modal="true"><button id="t1">a</button><button id="t2">b</button><button id="t3">c</button></div>',
    );
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Tab") return;
      e.preventDefault();
      const on = document.activeElement?.id;
      document.getElementById(on === "t1" ? "t2" : "t1")?.focus();
    });
  });
  const modal = await walk(page);
  rows.push(
    rec(
      "controls hold: a cycle inside an aria-modal is not flagged",
      "control",
      trapStory,
      "2.1.2",
      modal.cycle === 0 && modal.modal,
      JSON.stringify(modal),
    ),
  );
  save("control", rows);
  expect(failures(rows)).toBe("");
});

// ------------------------------------------------------------------------------------------------- zoom

const TABLE_STORIES = [
  "molecules-table--compact",
  "molecules-table--default",
  "molecules-table--reflow",
  "molecules-table--long-text",
  "molecules-table--grid",
];

interface Snap {
  readonly headers: string[];
  readonly cells: string[];
  readonly rows: number;
}
const snapshot = (page: Page): Promise<Snap> =>
  page.evaluate(() => {
    const clean = (s: string | null): string => (s ?? "").replace(/\s+/g, " ").trim();
    const headers = [...document.querySelectorAll("th")].map((e) => clean(e.textContent));
    const cells = [...document.querySelectorAll("td")].map((e) => clean(e.textContent));
    return { headers, cells, rows: document.querySelectorAll("tbody tr").length };
  });

interface Clip {
  readonly hard: string[];
  readonly ellipsis: string[];
}
const clipped = (page: Page): Promise<Clip> =>
  page.evaluate(() => {
    const hard: string[] = [];
    const ellipsis: string[] = [];
    for (const el of document.querySelectorAll("#storybook-root *")) {
      const s = getComputedStyle(el);
      const cls = String((el as HTMLElement).className);
      if (
        s.display === "none" ||
        el.closest("[aria-hidden='true']") ||
        cls.includes("visually-hidden")
      )
        continue;
      const h = el as HTMLElement;
      const clips = (o: string): boolean => o !== "visible" && o !== "auto" && o !== "scroll";
      const hx = h.scrollWidth > h.clientWidth + 1 && clips(s.overflowX);
      const vy = h.scrollHeight > h.clientHeight + 1 && clips(s.overflowY);
      if (!hx && !vy) continue;
      const text = (h.textContent ?? "").trim().slice(0, 30);
      const row = `${el.tagName.toLowerCase()}.${cls.split(" ")[0] ?? ""} "${text}"`;
      // A text-overflow ellipsis keeps the whole text in the DOM (read by AT, selectable); a hard clip loses it.
      (s.textOverflow === "ellipsis" && hx ? ellipsis : hard).push(row);
    }
    return { hard, ellipsis };
  });

/** Story hosts pin a fixed width (44rem, 1280 px); the table must meet the viewport, not the host's number. */
const unpinHosts = (page: Page): Promise<void> =>
  page.evaluate(() => {
    for (
      let e = document.querySelector(".cv-table")?.parentElement ?? null;
      e && e.id !== "storybook-root";
      e = e.parentElement
    ) {
      if (e.style.width !== "") e.style.width = "100%";
      if (e.style.maxWidth !== "") e.style.maxWidth = "100%";
    }
  });

for (const theme of THEMES) {
  test(`zoom: dense table, ${theme}`, async ({ page }) => {
    THEME = theme;
    test.setTimeout(300_000);
    const rows: Rec[] = [];
    for (const story of TABLE_STORIES) {
      await page.setViewportSize({ width: 1280, height: 800 });
      await open(page, story, theme, "compact");
      const base = await snapshot(page);
      for (const mode of ["200% zoom", "125% text scale"] as const) {
        if (mode === "200% zoom") {
          await page.setViewportSize({ width: 640, height: 400 });
        } else {
          await page.setViewportSize({ width: 1280, height: 800 });
          await page.evaluate(() => {
            document.documentElement.setAttribute("data-text-scale", "125");
          });
        }
        await unpinHosts(page);
        // State wait: the viewport has the target width and two frames have laid the page out.
        await expect
          .poll(() => page.evaluate(() => window.innerWidth), { timeout: 5_000 })
          .toBe(mode === "200% zoom" ? 640 : 1280);
        await page.evaluate(
          () =>
            new Promise<void>((done) => {
              requestAnimationFrame(() => requestAnimationFrame(() => done()));
            }),
        );
        const now = await snapshot(page);
        // The stacked layout prepends each cell's column label, so a cell keeps its text if it contains it.
        const after = [...now.headers, ...now.cells];
        const lost = [...base.headers, ...base.cells].filter(
          (t, i) => !(after[i] ?? "").includes(t),
        );
        rows.push(
          rec(
            `${mode}: no data lost`,
            "zoom",
            story,
            "1.4.4 (200 % zoom)",
            lost.length === 0 && now.rows === base.rows,
            `rows ${base.rows}->${now.rows}, cells changed ${lost.length}`,
            theme,
          ),
        );
        const pageScroll = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        // A table scrolls inside its own labelled region (data tables are exempt from 2-D scroll limits); the page never does.
        rows.push(
          rec(
            `${mode}: the page does not scroll horizontally`,
            "zoom",
            story,
            "1.4.4 (200 % zoom)",
            pageScroll <= 1,
            `overflow ${pageScroll}px`,
            theme,
          ),
        );
        const cut = await clipped(page);
        rows.push(
          rec(
            `${mode}: no hard-clipped text`,
            "zoom",
            story,
            "1.4.4 (200 % zoom)",
            cut.hard.length === 0,
            cut.hard.slice(0, 4).join("; ") ||
              `none (${cut.ellipsis.length} ellipsis truncation(s), full text in the DOM)`,
            theme,
          ),
        );
        if (story.endsWith("--reflow") && mode === "200% zoom") {
          const fit = await page.evaluate(() => {
            const shell = document.querySelector<HTMLElement>("[data-cmp='CMP-049']");
            const region = document.querySelector<HTMLElement>(".cv-table__region");
            return {
              layout: shell?.getAttribute("data-layout") ?? "table",
              over: (region?.scrollWidth ?? 0) - (region?.clientWidth ?? 0),
            };
          });
          rows.push(
            rec(
              `${mode}: the table stacks and its region does not scroll sideways`,
              "zoom",
              story,
              "1.4.4 (200 % zoom)",
              fit.layout === "stacked" && fit.over <= 0,
              `layout=${fit.layout}, region overflow ${fit.over}px`,
              theme,
            ),
          );
        }
      }
    }
    save(`zoom-${theme}`, rows);
    expect(failures(rows)).toBe("");
  });
}

// ----------------------------------------------------------------------------------------------- motion

interface Probe {
  readonly key: string;
  readonly path: string;
  readonly animation: string;
  readonly cue: string;
}

const motionProbe = (page: Page): Promise<Probe[]> =>
  page.evaluate(() => {
    const out: Probe[] = [];
    const pathOf = (el: Element): string => {
      const parts: string[] = [];
      for (
        let e: Element | null = el;
        e && e.id !== "storybook-root" && e !== document.body;
        e = e.parentElement
      )
        parts.push(String([...(e.parentElement?.children ?? [])].indexOf(e)));
      return `${el.closest("#storybook-root") ? "r" : "b"}:${parts.join("/")}`;
    };
    for (const el of document.querySelectorAll(
      "#storybook-root *, body > *:not(#storybook-root) *",
    )) {
      // Storybook's own chrome (loader, preview blocks: sb-*) is not the design system.
      let chrome = false;
      for (let e: Element | null = el; e && e !== document.body; e = e.parentElement) {
        if (
          String(e.getAttribute("class") ?? "")
            .split(" ")
            .some((c) => c.startsWith("sb-"))
        )
          chrome = true;
      }
      if (chrome) continue;
      for (const pseudo of [null, "::before", "::after"] as const) {
        const s = getComputedStyle(el, pseudo);
        if (s.animationName === "none" || s.animationName === "") continue;
        const key = `${el.tagName.toLowerCase()}.${String((el as HTMLElement).className).split(" ")[0] ?? ""}${pseudo ?? ""}`;
        const host = el.closest("[role],[aria-label],[aria-busy],[data-state]") ?? el;
        const text = (el.textContent ?? "").trim().slice(0, 30);
        const cue = [
          text !== "" ? `text="${text}"` : "",
          host.getAttribute("aria-label") !== null
            ? `label="${host.getAttribute("aria-label") ?? ""}"`
            : "",
          host.getAttribute("role") !== null ? `role=${host.getAttribute("role") ?? ""}` : "",
          host.getAttribute("aria-valuenow") !== null
            ? `valuenow=${host.getAttribute("aria-valuenow") ?? ""}`
            : "",
          host.getAttribute("aria-busy") !== null ? "aria-busy" : "",
        ]
          .filter((x) => x !== "")
          .join(" ");
        out.push({ key, path: pathOf(el), animation: s.animationName, cue });
      }
    }
    return out;
  });

/** Whether the element at a probe path shows its end state: displayed, visible, opaque, with a box. */
const endStates = (page: Page, paths: readonly string[]): Promise<Record<string, boolean>> =>
  page.evaluate((list) => {
    const res: { [k: string]: boolean } = {};
    for (const path of list) {
      const [scope, rest = ""] = path.split(":");
      let el: Element | null =
        scope === "r" ? document.querySelector("#storybook-root") : document.body;
      if (scope === "b") {
        const idx = rest.split("/").reverse();
        el = document.body.children[Number(idx[0])] ?? null;
        for (const i of idx.slice(1)) el = el?.children[Number(i)] ?? null;
      } else {
        for (const i of rest
          .split("/")
          .reverse()
          .filter((x) => x !== ""))
          el = el?.children[Number(i)] ?? null;
      }
      if (!el) {
        res[path] = false;
        continue;
      }
      const s = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      res[path] =
        s.display !== "none" &&
        s.visibility !== "hidden" &&
        Number(s.opacity) > 0 &&
        (r.width > 0 || r.height > 0);
    }
    return res;
  }, paths);

const pinsMotion = (page: Page): Promise<boolean> =>
  page.evaluate(() => {
    const preview = (window as unknown as { __STORYBOOK_PREVIEW__?: { currentRender?: unknown } })
      .__STORYBOOK_PREVIEW__;
    const render = preview?.currentRender as
      { story?: { storyGlobals?: { [k: string]: unknown } } } | undefined;
    return typeof render?.story?.storyGlobals?.["motion"] === "string";
  });

const MOTION_IDS = IDS;
const MCHUNK = Math.ceil(MOTION_IDS.length / 8);
for (const theme of THEMES)
  for (let i = 0; i < MOTION_IDS.length; i += MCHUNK) {
    const chunk = MOTION_IDS.slice(i, i + MCHUNK);
    test(`motion probe ${String(i / MCHUNK + 1)}, ${theme}`, async ({ page }) => {
      test.setTimeout(900_000);
      THEME = theme;
      const rows: Rec[] = [];
      for (const story of chunk) {
        await page.emulateMedia({ reducedMotion: "no-preference" });
        await open(page, story, theme, "compact", "off");
        const safe = await motionProbe(page);
        await page.emulateMedia({ reducedMotion: "reduce" });
        await open(page, story, theme, "compact", "on");
        if (await pinsMotion(page)) {
          // The story pins its own motion state (a motion-safe or recipe demo): the override cannot apply to it.
          rows.push(
            rec(
              "reduced motion: story pins its own motion state, not applicable",
              "motion",
              story,
              "2.3.3",
              true,
              `pinned; ${safe.length} animated element(s) by design`,
              theme,
              true,
            ),
          );
          continue;
        }
        const reduced = await motionProbe(page);
        const reducedPaths = new Set(reduced.map((p) => p.path));
        const lost = safe.filter((p) => !reducedPaths.has(p.path));
        const ends = await endStates(
          page,
          lost.map((p) => p.path),
        );
        const hasState = await page.evaluate(
          () =>
            document.querySelector(
              "[role=dialog],[role=alertdialog],[role=status],[role=progressbar],[role=alert]",
            ) !== null,
        );
        // (a) nothing the reduced render animates; (b) every element whose motion was removed is in its end
        // state, and the change it conveyed has a non-motion cue signal: its own text / name / value, or any
        // live, dialog or progress role anywhere on the page. That last clause is page-level: it can pass when an
        // unrelated such element exists, so the check is a DOM signal, not proof the change is perceivable.
        const hidden = lost.filter((p) => ends[p.path] !== true);
        const noCue = lost.filter((p) => p.cue === "" && !hasState);
        // The recipe demo stories draw the safe value beside the reduce value on purpose: the reduce half must stop.
        const demo = story.startsWith("foundations-motion-recipes--");
        rows.push(
          rec(
            "reduced motion: no animation survives data-motion=reduce",
            "motion",
            story,
            "2.3.3",
            demo ? reduced.length < safe.length : reduced.length === 0,
            `safe animated ${safe.length}, reduced animated ${reduced.length}${
              reduced.length > 0
                ? `; still: ${reduced
                    .slice(0, 3)
                    .map((p) => `${p.key} ${p.animation}`)
                    .join(", ")}`
                : ""
            }`,
            theme,
          ),
        );
        rows.push(
          rec(
            "reduced motion: elements whose motion was removed show their end state",
            "motion",
            story,
            "2.3.3",
            hidden.length === 0,
            hidden
              .slice(0, 3)
              .map((p) => p.key)
              .join(", ") || `${lost.length} checked`,
            theme,
          ),
        );
        rows.push(
          rec(
            "reduced motion: the change keeps a non-motion cue",
            "motion",
            story,
            "1.3.1 / 4.1.3",
            noCue.length === 0,
            noCue
              .slice(0, 3)
              .map((p) => p.key)
              .join(", ") || `${lost.length} checked`,
            theme,
          ),
        );
      }
      save(`motion-${theme}-${String(i / MCHUNK + 1).padStart(2, "0")}`, rows);
      expect(failures(rows)).toBe("");
    });
  }
