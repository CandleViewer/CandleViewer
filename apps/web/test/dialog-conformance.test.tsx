/**
 * E47-S05 (#1319) slice 2: the dialog conformance matrix (A11Y-P-01, WCAG 2.4.3, APG Dialog (Modal)).
 * Every dialog built in apps/web, and the packages/ui dialogs it uses, is mounted from a real opener
 * and held to the same six observations: focus moves in on open, Tab and Shift+Tab stay inside, Esc
 * does what the dialog's contract says (cancel, or nothing for a lock), focus returns to the opener
 * and never to body, the dialog has an accessible name, and axe finds nothing serious. A source scan
 * fails when a dialog is added to apps/web/src without a row here.
 *
 * A row's `gaps` names an observation that does not hold today, with the reason; the matrix then
 * asserts the gap is still there, so fixing it forces the entry out. The pinned regressions
 * (A11Y-F-0013, F-0026, F-0027) are at the end.
 */
import { createRequire } from "node:module";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { useRef, useState, type JSX } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { ConfirmDialog, Dialog } from "@candleviewer/ui";
import { SEARCH_TRIGGER_ID } from "../src/features/app-shell/TopBar";
import { CoachMarkTour } from "../src/features/onboarding/CoachMarkTour";
import { SessionLockDialog } from "../src/features/session/SessionLockDialog";
import { SessionExpiredCard, SignOutConfirm } from "../src/features/session/SessionLockEscapes";
import { SessionTimeoutWarning } from "../src/features/session/SessionTimeoutWarning";
import { SessionsSection } from "../src/features/session/SessionsSection";
import type { SessionsApi, UserSession } from "../src/features/session/sessionsApi";
import { StepUpDialog } from "../src/features/stepUp/StepUpDialog";
import { VersionDialogSlot } from "../src/features/system-states/VersionDialog";
import { resetVersionReports } from "../src/features/system-states/versionMismatch";
import { Cheatsheet } from "../src/keymap/Cheatsheet";
import { handleWsError } from "../src/lib/ws/errorHandler";
import { WsErrorHost } from "../src/lib/ws/WsErrorHost";
import { resetShellState, setShellState } from "../src/shell/bootstrap/store";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

type Role = "dialog" | "alertdialog";
type Dim = "focusIn" | "trap" | "escape" | "return" | "scrim";

interface Spies {
  readonly confirm: Mock;
  readonly cancel: Mock;
}
interface Handle {
  /** The element that has focus when the dialog is opened, and that focus must come back to. */
  readonly opener: () => Promise<HTMLElement>;
  readonly open: () => void | Promise<void>;
  /** Closes it from the host, for a dialog that ignores Esc. */
  readonly close?: () => void;
}
interface Row {
  readonly id: string;
  readonly role: Role;
  /** `cancels`: Esc closes it and confirms nothing. `inert`: Esc does nothing (a lock). */
  readonly esc: "cancels" | "inert";
  /** A press on the scrim must not dismiss; `guard` rows also keep it from taking focus (F-0013). */
  readonly scrim: "none" | "guard";
  /** Runs before Esc: puts the dialog in its most committed state (a typed confirm that matches). */
  readonly beforeEsc?: () => void;
  readonly gaps?: Partial<Record<Dim, string>>;
  readonly mount: (spies: Spies) => Handle;
}

/** The page under the dialog: a control before the opener, the opener, one after it, the dialog. */
function simple(
  ui: (p: { open: boolean; spies: Spies; cancel: () => void }) => JSX.Element | null,
  opts: { openerId?: string; onOpen?: () => void } = {},
): (spies: Spies) => Handle {
  return (spies) => {
    let set: (open: boolean) => void = () => undefined;
    function Host(): JSX.Element {
      const [open, setOpen] = useState(false);
      set = setOpen;
      const cancel = (): void => {
        spies.cancel();
        setOpen(false);
      };
      return (
        <>
          <button type="button">Before</button>
          <button
            type="button"
            id={opts.openerId}
            onClick={() => {
              opts.onOpen?.();
              setOpen(true);
            }}
          >
            Open
          </button>
          <button type="button">After</button>
          {ui({ open, spies, cancel })}
        </>
      );
    }
    render(<Host />);
    return {
      opener: () => Promise.resolve(screen.getByRole("button", { name: "Open" })),
      open: () => void fireEvent.click(screen.getByRole("button", { name: "Open" })),
      close: () => act(() => set(false)),
    };
  };
}

const SESSIONS: readonly UserSession[] = [
  {
    id: "00000000-0000-4000-8000-000000000002",
    device_name: "Laptop",
    ip: null,
    user_agent: "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0",
    created_at: "2026-10-27T08:00:00+00:00",
    last_seen_at: "2026-10-27T09:02:00+00:00",
    expires_at: "2026-10-27T20:00:00+00:00",
    current: false,
  },
];
const sessionsApi = (): SessionsApi => ({
  list: () => Promise.resolve({ kind: "ok" as const, items: SESSIONS }),
  revoke: vi.fn(() => Promise.resolve({ kind: "done" as const })),
  signOutEverywhere: vi.fn(() => Promise.resolve({ kind: "done" as const })),
  endSession: vi.fn(),
});

const field = (label: RegExp | string): HTMLElement => screen.getByLabelText(label);

const ROWS: readonly Row[] = [
  {
    id: "StepUpDialog (code only)",
    role: "alertdialog",
    esc: "cancels",
    scrim: "guard",
    mount: simple(({ open, spies, cancel }) =>
      open ? (
        <StepUpDialog
          actionSummary="Flatten BTCUSDT"
          target={null}
          onSubmit={spies.confirm}
          onCancel={cancel}
        />
      ) : null,
    ),
  },
  {
    id: "StepUpDialog (typed confirm)",
    role: "alertdialog",
    esc: "cancels",
    scrim: "guard",
    beforeEsc: () => {
      fireEvent.change(field(/password/iu), { target: { value: "hunter2hunter2" } });
      fireEvent.change(field(/6-digit|code/iu), { target: { value: "123456" } });
      fireEvent.change(field(/^Type|FLATTEN/u), { target: { value: "FLATTEN" } });
    },
    mount: simple(({ open, spies, cancel }) =>
      open ? (
        <StepUpDialog
          actionSummary="Flatten all"
          target="FLATTEN"
          onSubmit={spies.confirm}
          onCancel={cancel}
        />
      ) : null,
    ),
  },
  {
    id: "SessionLockDialog",
    role: "alertdialog",
    esc: "inert",
    scrim: "guard",
    mount: simple(({ open, spies }) =>
      open ? (
        <SessionLockDialog
          idleMinutes={15}
          phase="locked"
          onUnlock={spies.confirm}
          onSignOut={spies.confirm}
        />
      ) : null,
    ),
  },
  {
    id: "SignOutConfirm",
    role: "alertdialog",
    esc: "cancels",
    scrim: "guard",
    gaps: {
      return:
        "a view swap, not an overlay: Back remounts SessionLockDialog, which focuses its password (SessionLockHost)",
    },
    mount: simple(({ open, spies, cancel }) =>
      open ? (
        <SignOutConfirm busy={false} failed={false} onConfirm={spies.confirm} onBack={cancel} />
      ) : null,
    ),
  },
  {
    id: "SessionExpiredCard",
    role: "alertdialog",
    esc: "inert",
    scrim: "guard",
    mount: simple(({ open, spies }) =>
      open ? <SessionExpiredCard onSignIn={spies.confirm} /> : null,
    ),
  },
  {
    id: "SessionTimeoutWarning",
    role: "alertdialog",
    esc: "cancels",
    scrim: "none",
    mount: simple(({ open, spies, cancel }) =>
      open ? (
        <SessionTimeoutWarning expiresInSec={60} onExtend={spies.confirm} onDismiss={cancel} />
      ) : null,
    ),
  },
  {
    id: "SessionsSection revoke confirm",
    role: "alertdialog",
    esc: "cancels",
    scrim: "guard",
    mount: (spies) => {
      const api = sessionsApi();
      render(<SessionsSection api={api} />);
      const opener = (): Promise<HTMLElement> =>
        screen.findByRole("button", { name: /^Revoke Laptop/u });
      // its Esc path is the dialog's own Cancel: a spy cannot see it, so watch the revoke call
      api.revoke = spies.confirm as SessionsApi["revoke"];
      return { opener, open: async () => void fireEvent.click(await opener()) };
    },
  },
  {
    id: "Cheatsheet",
    role: "dialog",
    esc: "cancels",
    scrim: "none",
    mount: simple(({ open, cancel }) => (open ? <Cheatsheet onClose={cancel} /> : null)),
  },
  {
    id: "CoachMarkTour",
    role: "dialog",
    esc: "cancels",
    scrim: "none",
    gaps: {
      trap: "non-modal on purpose: the panic buttons are never blocked by the tour (SCR-018)",
    },
    mount: simple(({ open, cancel }) => (open ? <CoachMarkTour onClose={cancel} /> : null)),
  },
  {
    id: "VersionDialog (via VersionDialogSlot)",
    role: "alertdialog",
    esc: "cancels",
    scrim: "none",
    // focus returns to the TopBar's search trigger by design (E10-D04 §13.2), the opener here
    mount: simple(() => <VersionDialogSlot />, {
      openerId: SEARCH_TRIGGER_ID,
      onOpen: () => setShellState({ serverProtocol: "cv.v0", serverVersion: "9.9.9" }),
    }),
  },
  {
    id: "ui Dialog (dialog)",
    role: "dialog",
    esc: "cancels",
    scrim: "none",
    mount: simple(({ open, cancel }) => (
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) cancel();
        }}
        title="Rename workspace"
        footer={<button type="button">Save</button>}
      >
        <label>
          Name
          <input type="text" />
        </label>
      </Dialog>
    )),
  },
  {
    id: "ui ConfirmDialog (typed)",
    role: "alertdialog",
    esc: "cancels",
    scrim: "none",
    beforeEsc: () => fireEvent.change(field(/FLATTEN/u), { target: { value: "FLATTEN" } }),
    mount: simple(({ open, spies, cancel }) => (
      <ConfirmDialog
        open={open}
        title="Flatten BTCUSDT?"
        confirmLabel="Flatten BTCUSDT"
        variant="typed"
        typedConfirmValue="FLATTEN"
        onConfirm={spies.confirm}
        onCancel={cancel}
      />
    )),
  },
  {
    id: "WsErrorHost fatal modal",
    role: "alertdialog",
    esc: "cancels",
    scrim: "none",
    gaps: {
      focusIn: "no focus management: the modal mounts with focus left on the page",
      trap: "no Tab containment under aria-modal",
      escape: "no Esc handler: only the Dismiss button closes it",
      return: "nothing moves focus in, so nothing returns it",
    },
    mount: simple(() => <WsErrorHost />, {
      onOpen: () => handleWsError({ t: "err", p: { code: "auth_failed" } }),
    }),
  },
];

const TABBABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])';

const tabbables = (): HTMLElement[] =>
  Array.from(document.querySelectorAll<HTMLElement>(TABBABLE)).filter(
    (el) => el.closest('[inert], [aria-hidden="true"]') === null,
  );

/** One Tab press as a browser does it: the keydown first, then the move, unless a handler took it. */
function tab(shift: boolean): void {
  const at = document.activeElement ?? document.body;
  if (!fireEvent.keyDown(at, { key: "Tab", shiftKey: shift })) return;
  const stops = tabbables();
  const after = (el: HTMLElement): boolean =>
    Boolean(at.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
  const next = shift
    ? [...stops].reverse().find((el) => !after(el) && el !== at)
    : stops.find((el) => after(el));
  (next ?? (shift ? stops[stops.length - 1] : stops[0]))?.focus();
}

/** Gives an opening dialog its tick to take focus; a dialog that never does is a finding, not a throw. */
const settle = (el: HTMLElement): Promise<void> =>
  waitFor(() => expect(el.contains(document.activeElement)).toBe(true), { timeout: 150 }).catch(
    () => undefined,
  );

const dialogOf = (role: Role): HTMLElement => screen.getByRole(role);

async function openRow(row: Row): Promise<{ handle: Handle; opener: HTMLElement; spies: Spies }> {
  const spies = { confirm: vi.fn(), cancel: vi.fn() };
  const handle = row.mount(spies);
  const opener = await handle.opener();
  opener.focus();
  await handle.open();
  await screen.findByRole(row.role);
  return { handle, opener, spies };
}

const OBSERVE: Record<Dim, (row: Row) => Promise<boolean>> = {
  focusIn: async (row) => {
    await openRow(row);
    const el = dialogOf(row.role);
    await settle(el);
    return el.contains(document.activeElement) && document.activeElement !== document.body;
  },
  trap: async (row) => {
    await openRow(row);
    const el = dialogOf(row.role);
    await settle(el);
    const presses = tabbables().length + 2;
    for (const shift of [false, true]) {
      for (let i = 0; i < presses; i += 1) {
        tab(shift);
        if (!el.contains(document.activeElement)) return false;
      }
    }
    return true;
  },
  escape: async (row) => {
    const { spies } = await openRow(row);
    const el = dialogOf(row.role);
    await settle(el);
    row.beforeEsc?.();
    fireEvent.keyDown(document.activeElement ?? el, { key: "Escape" });
    // Esc is never a confirmation, even with the typed field matching
    if (spies.confirm.mock.calls.length > 0) return false;
    if (row.esc === "inert") return screen.queryByRole(row.role) !== null;
    try {
      await waitFor(() => expect(screen.queryByRole(row.role)).toBeNull());
      return true;
    } catch {
      return false;
    }
  },
  return: async (row) => {
    const { handle, opener } = await openRow(row);
    const el = dialogOf(row.role);
    await settle(el);
    if (row.esc === "cancels") fireEvent.keyDown(document.activeElement ?? el, { key: "Escape" });
    if (screen.queryByRole(row.role) !== null) handle.close?.();
    try {
      await waitFor(() => expect(screen.queryByRole(row.role)).toBeNull());
      await waitFor(() => expect(document.activeElement).toBe(opener));
      return true;
    } catch {
      return false;
    }
  },
  scrim: async (row) => {
    const { spies } = await openRow(row);
    const el = dialogOf(row.role);
    await settle(el);
    const scrim = el.closest(".cv-dialog__scrim") ?? el.parentElement;
    if (scrim === null || scrim === document.body) return row.scrim === "none";
    const taken = !fireEvent.mouseDown(scrim);
    fireEvent.mouseUp(scrim);
    fireEvent.click(scrim);
    const stays = screen.queryByRole(row.role) !== null && spies.confirm.mock.calls.length === 0;
    return row.role === "alertdialog" ? stays && (row.scrim !== "guard" || taken) : true;
  },
};

beforeEach(() => {
  resetShellState();
  resetVersionReports();
});
afterEach(() => {
  resetShellState();
  vi.restoreAllMocks();
});

describe.each(ROWS)("dialog conformance: $id", (row) => {
  for (const dim of ["focusIn", "trap", "escape", "return", "scrim"] as const) {
    const gap = row.gaps?.[dim];
    const title = {
      focusIn: "focus moves into the dialog on open",
      trap: "Tab and Shift+Tab stay inside",
      escape: row.esc === "cancels" ? "Esc cancels and never confirms" : "Esc does not dismiss",
      return: "focus returns to the opener, never body",
      scrim: "a scrim press does not dismiss an alertdialog or take focus",
    }[dim];
    it(gap === undefined ? title : `known gap (${gap}): ${title} does not hold`, async () => {
      const held = await OBSERVE[dim](row);
      expect(held, `${row.id}: ${dim}`).toBe(gap === undefined);
    });
  }

  it("has an accessible name and a serious-free axe run", async () => {
    await openRow(row);
    expect(screen.getByRole(row.role, { name: /\S/u })).toBeTruthy();
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});

/** Dialog sources in apps/web/src, and where each one is held to the matrix. */
const COVERED: Readonly<Record<string, string>> = {
  "features/stepUp/StepUpDialog.tsx": "matrix: StepUpDialog rows",
  "features/session/SessionLockDialog.tsx": "matrix: SessionLockDialog",
  "features/session/SessionLockEscapes.tsx": "matrix: SignOutConfirm, SessionExpiredCard",
  "features/session/SessionTimeoutWarning.tsx": "matrix: SessionTimeoutWarning",
  "features/session/SessionsSection.tsx": "matrix: SessionsSection revoke confirm",
  "keymap/Cheatsheet.tsx": "matrix: Cheatsheet",
  "features/onboarding/CoachMarkTour.tsx": "matrix: CoachMarkTour",
  "features/system-states/VersionDialog.tsx": "matrix: VersionDialog",
  "lib/ws/WsErrorHost.tsx": "matrix: WsErrorHost fatal modal",
  "features/symbol-search/SymbolSearch.tsx":
    "ui Dialog row (the mechanism); focus in and back in symbol-search/SymbolSearch.test.tsx",
};
const DIALOG_SOURCE = /role="(?:alert)?dialog"|<Dialog\b|<ConfirmDialog\b|aria-modal/u;

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return sources(p);
    return /\.tsx$/u.test(e.name) && !/\.(stories|test)\.tsx$/u.test(e.name) ? [p] : [];
  });
}

describe("dialog conformance: nothing built is missing", () => {
  it("every dialog source in apps/web/src has a row, or is named here with its reason", () => {
    const root = join(import.meta.dirname, "..", "src");
    const found = sources(root)
      .filter((p) => DIALOG_SOURCE.test(readFileSync(p, "utf8")))
      .map((p) => relative(root, p).split("\\").join("/"))
      .sort();
    expect(found).toEqual(Object.keys(COVERED).sort());
  });
});

describe("pinned regressions", () => {
  it("A11Y-F-0013: a press on the step-up scrim neither dismisses nor takes focus off the dialog", async () => {
    const spies = { confirm: vi.fn(), cancel: vi.fn() };
    const handle = ROWS[0]!.mount(spies);
    (await handle.opener()).focus();
    await handle.open();
    const el = dialogOf("alertdialog");
    await settle(el);
    const scrim = el.parentElement!;
    expect(fireEvent.mouseDown(scrim)).toBe(false); // default prevented: a browser would not blur
    fireEvent.click(scrim);
    expect(spies.cancel).not.toHaveBeenCalled();
    expect(el.contains(document.activeElement)).toBe(true);
  });

  it("A11Y-F-0026: the cheatsheet is a modal dialog: focus in on Close, trapped, Esc closes, focus back", async () => {
    const row = ROWS.find((r) => r.id === "Cheatsheet")!;
    const { opener } = await openRow(row);
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    expect(dialogOf("dialog")).toHaveAttribute("aria-modal", "true");
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(opener).toHaveFocus();
  });

  it("A11Y-F-0027: a tour that auto-opened (focus on body) returns focus to the host's control", () => {
    function Host(): JSX.Element {
      const [open, setOpen] = useState(true);
      const home = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={home} type="button">
            Take the tour
          </button>
          {open ? <CoachMarkTour onClose={() => setOpen(false)} returnFocusTo={home} /> : null}
        </>
      );
    }
    (document.activeElement as HTMLElement | null)?.blur();
    expect(document.activeElement).toBe(document.body);
    render(<Host />);
    expect(screen.getByRole("dialog")).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Take the tour" })).toHaveFocus();
  });
});
