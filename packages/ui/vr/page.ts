/**
 * The capture's in-page steps (E05-T04). Playwright serialises `storyState` and `settleForCapture` into the
 * story iframe, so neither may close over anything: no imports at run time, no module constants.
 * `cellProblem` and `NOT_CAPTURED` are the spec's, in Node.
 */

type Globals = Readonly<Record<string, unknown>>;

/** The root attributes E05-T02's theme runtime writes on `<html>`. */
export interface RootAttributes {
  readonly theme: string;
  readonly density: string;
  readonly motion: string;
}

/** How Storybook left a story once its render settled. */
export interface StoryState {
  readonly status: "rendered" | "play-failed" | "errored" | "missing";
  readonly message: string;
  /** The globals Storybook took from the URL (the toolbar globals), before any the story pins. */
  readonly globals: Globals;
  /** The globals the story pins itself (story-level `globals`), which win over the URL's. */
  readonly pinned: Globals;
}

/** The slice of Storybook 10's `PreviewWeb` the capture reads (not a public API; the lockfile pins it). */
interface PreviewHandle {
  readonly currentRender?: {
    readonly phase?: string;
    readonly story?: { readonly storyGlobals?: Globals };
  };
  readonly storyStoreValue?: { readonly userGlobals?: { get(): Globals } };
}

/** Storybook's addons channel keeps the last payload of every event it emitted (`last`). */
interface ChannelHandle {
  last?(event: string): readonly unknown[] | undefined;
}

/**
 * Polled until it returns a state: Storybook's error display, its "no preview" page, or the end of the
 * story's render. `finished` comes after the play function, Storybook's own wait for finite animations, and
 * `afterEach`, so a play function's last step is on screen. Storybook 10.6 reaches `finished` after a play
 * function threw too (its core preview sets `throwPlayFunctionExceptions: false`), so the channel's record
 * of the play's exception, its unhandled errors and the story's finished status decide `play-failed`.
 */
export function storyState(): StoryState | null {
  const classes = document.body.classList;
  const text = (id: string): string => document.getElementById(id)?.textContent?.trim() ?? "";
  if (classes.contains("sb-show-errordisplay")) {
    const message = `${text("error-message")} ${text("error-stack")}`;
    return { status: "errored", message, globals: {}, pinned: {} };
  }
  if (classes.contains("sb-show-nopreview")) {
    const message = "Storybook has no story with this id";
    return { status: "missing", message, globals: {}, pinned: {} };
  }
  // The preview's own global: a window property TypeScript's DOM types do not declare.
  const preview = (window as unknown as { __STORYBOOK_PREVIEW__?: PreviewHandle })
    .__STORYBOOK_PREVIEW__;
  const render = preview?.currentRender;
  if (render?.phase !== "finished") return null;
  const globals = preview?.storyStoreValue?.userGlobals?.get() ?? {};
  const pinned = render.story?.storyGlobals ?? {};
  const channel = (window as unknown as { __STORYBOOK_ADDONS_CHANNEL__?: ChannelHandle })
    .__STORYBOOK_ADDONS_CHANNEL__;
  const last = (event: string): unknown => channel?.last?.(event)?.[0];
  const field = (value: unknown, key: string): unknown =>
    typeof value === "object" && value !== null
      ? (value as Record<string, unknown>)[key]
      : undefined;
  // Storybook's serialised error: `{ name, message, stack }`.
  const said = (error: unknown): string =>
    `${String(field(error, "name") ?? "Error")}: ${String(field(error, "message") ?? error)}`;
  const failed = (message: string): StoryState => ({
    status: "play-failed",
    message,
    globals,
    pinned,
  });
  const threw = last("playFunctionThrewException");
  if (threw !== undefined) return failed(said(threw));
  const unhandled = last("unhandledErrorsWhilePlaying");
  if (Array.isArray(unhandled) && unhandled.length > 0) {
    const more = unhandled.length > 1 ? ` (and ${unhandled.length - 1} more)` : "";
    return failed(`unhandled while playing: ${said(unhandled[0])}${more}`);
  }
  const finished = last("storyFinished");
  if (field(finished, "status") === "error") {
    const reports = field(finished, "reporters");
    const names = (Array.isArray(reports) ? reports : [])
      .filter((report) => field(report, "status") === "failed")
      .map((report) => String(field(report, "type")));
    const which = names.length > 0 ? ` (failed: ${names.join(", ")})` : "";
    return failed(`Storybook finished the story with status error${which}`);
  }
  return { status: "rendered", message: "", globals, pinned };
}

/** The annotation of a cell that fails before its capture: the job summary lists it apart from diffs. */
export const NOT_CAPTURED = "not-captured";

/**
 * Why a cell cannot be captured, or undefined when Storybook rendered it: the error the cell fails with, so a
 * failed play is a named cell error, never a screenshot of the state the play stopped in. In Node only.
 */
export function cellProblem(state: StoryState): string | undefined {
  switch (state.status) {
    case "rendered":
      return undefined;
    case "play-failed":
      return `play function failed: ${state.message}`;
    case "errored":
      return `Storybook showed its error display: ${state.message}`;
    case "missing":
      return state.message;
  }
}

/**
 * Once the story finished: waits for its fonts, ends what still animates (a story that pins motion off
 * opts out of the reduced-motion attribute; this does what Playwright's `animations: "disabled"` does at the
 * shot, before the clip is measured), scrolls to the top and returns the root attributes the runtime wrote.
 */
export async function settleForCapture(): Promise<RootAttributes> {
  await document.fonts.ready;
  for (const animation of document.getAnimations()) {
    try {
      animation.finish();
    } catch {
      animation.cancel(); // an infinite animation has no end to finish at
    }
  }
  window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  const { theme = "", density = "", motion = "" } = document.documentElement.dataset;
  return { theme, density, motion };
}
