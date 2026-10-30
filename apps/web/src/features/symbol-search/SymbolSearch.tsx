/**
 * SCR-102 Symbol search (E08-S09; E08-D05 §6, §8, §9.2, D-10, D-11): CMP-043 over CMP-160 and CMP-213, opened from
 * the TopBar's symbol trigger once a workspace has registered its opener. The shell keeps the TopBar, the banner slot,
 * the StatusBar and its live regions out of the inert page and the scrim (AppShell); a press there, or on the open
 * trigger, closes it without commit.
 */
import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type JSX,
  type KeyboardEvent,
  type RefObject,
} from "react";
import {
  Dialog,
  EmptyState,
  Kbd,
  Spinner,
  SymbolPicker,
  SymbolSearchInput,
} from "@candleviewer/ui";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { announce, forget } from "../app-shell/announcer";
import { COPY, SEARCH_TITLE, commitSentence, keyHints, targetWords } from "./copy";
import type { InstrumentIndex } from "./instrumentIndex";
import { stopKeys } from "./keys";
import { RESULT_CAP } from "./ranking";
import {
  closeSymbolSearch,
  openSymbolSearch,
  rememberSymbol,
  useSymbolSearch,
  type SymbolOpener,
  type SymbolTarget,
} from "./searchSession";
import { searchView, type SearchEmpty } from "./searchView";

/** The trigger's id: its own press toggles, so the TopBar-press close leaves it alone. */
export const SYMBOL_TRIGGER_ID = "cv-symbol-trigger";
/** The commit's one key in the shell announcer: forgotten before each commit, so each is said and none is kept. */
const COMMIT_KEY = "symbol-search:commit";
/** §5's footer line ("Showing 50 of 213 results — keep typing to narrow"). */
const showing = (total: number): string =>
  `Showing ${String(RESULT_CAP)} of ${String(total)} results — keep typing to narrow`;

const LINE: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-inset-sm)",
  margin: 0,
  color: "var(--color-text-secondary)",
  font: "var(--type-ui-caption-font-weight) var(--type-ui-caption-font-size) / var(--type-ui-caption-line-height) var(--type-ui-caption-font-family)",
};

/** §5: min(cap, ⌊(0.7 × h − chrome) / row⌋): 16 / 11 rows at 1280 × 800, compact / comfortable. */
export function visibleRows(height: number, comfortable: boolean): number {
  const [row, chrome, cap] = comfortable ? [32, 208, 12] : [24, 168, 16];
  return Math.max(1, Math.min(cap, Math.floor((0.7 * height - chrome) / row)));
}

/** The TopBar's CMP-219 on the bound pane's symbol (SCR-010); with no pane bound the TopBar draws none in its place. */
export function SymbolSearchTrigger({ target }: { readonly target: SymbolTarget }): JSX.Element {
  const open = useSymbolSearch((s) => s.open);
  // D-11, §9.2: a press on the open trigger closes SCR-102 without commit (CR-B2BD-04); closed, it opens it.
  const toggle = (): void => (open ? closeSymbolSearch() : openSymbolSearch());
  return (
    <SymbolPicker
      id={SYMBOL_TRIGGER_ID}
      value={target.symbol}
      interval={target.intervalWords}
      expanded={open}
      onOpen={toggle}
    />
  );
}

/**
 * Mounted once in the shell: SCR-102, while the index runs and a workspace can take a commit. `main` is the shell's
 * `main`, where focus goes when neither the trigger nor the target panel is left to take it (§9.2).
 */
export function SymbolSearchHost({
  main,
}: {
  readonly main: RefObject<HTMLElement | null>;
}): JSX.Element | null {
  const index = useSymbolSearch((s) => s.index);
  const opener = useSymbolSearch((s) => s.opener);
  const open = useSymbolSearch((s) => s.open);
  const opened = useSymbolSearch((s) => s.opened);
  if (index === null || opener === null) return null;
  return <SymbolSearchDialog key={opened} index={index} opener={opener} open={open} main={main} />;
}

interface DialogProps {
  readonly index: InstrumentIndex;
  readonly opener: SymbolOpener;
  readonly open: boolean;
  readonly main: RefObject<HTMLElement | null>;
}

function SymbolSearchDialog({ index, opener, open, main }: DialogProps): JSX.Element {
  const snapshot = useSyncExternalStore(index.subscribe, index.getSnapshot);
  const recent = useSymbolSearch((s) => s.recent);
  const link = useShellSelector((s) => s.connection.kind);
  const [query, setQuery] = useState("");
  // The waits a snapshot names count from its arrival, so no sentence ticks while typing.
  const [arrival, setArrival] = useState(() => ({ snapshot, at: Date.now() }));
  if (arrival.snapshot !== snapshot) setArrival({ snapshot, at: Date.now() });
  const rows = useMemo(() => {
    const density = document.documentElement.getAttribute("data-density");
    return visibleRows(window.innerHeight, density === "comfortable");
  }, []);
  const targetId = useId();
  const hintsId = useId();
  const view = searchView(query, snapshot, recent, arrival.at);
  const { target } = opener;
  const words = targetWords(target);
  const failed = view.empty?.kind === "failed";
  const wasFailed = useRef(failed);
  // §9.2: closing returns focus to the trigger, else the target panel, else the shell's `main`, never to the page.
  // Read when the dialog closes or unmounts, so a pane unbound or a workspace gone while it is open is seen.
  const fallback = useMemo<RefObject<HTMLElement | null>>(
    () => ({
      get current() {
        const panel = opener.panel?.current ?? null;
        return panel?.isConnected === true ? panel : main.current;
      },
    }),
    [opener, main],
  );

  // D-11, §9.2: a press outside the dialog (the TopBar, the banner slot, the StatusBar, which the shell keeps live
  // and out of the scrim's band) closes it without commit; the trigger's own press toggles.
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event: PointerEvent): void => {
      const node = event.target instanceof Element ? event.target : null;
      if (node?.closest(`#${SYMBOL_TRIGGER_ID}, [data-cv-layer]`) === null) closeSymbolSearch();
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [open]);

  // §9.2: Retry now goes with the failure when the list comes, and focus never falls to the page: it goes back to
  // the input, where the dialog starts.
  useLayoutEffect(() => {
    const was = wasFailed.current;
    wasFailed.current = failed;
    if (!was || failed) return;
    const card = document.getElementById(targetId)?.closest('[role="dialog"]');
    if (card?.contains(document.activeElement) === false)
      card.querySelector<HTMLElement>('[role="combobox"]')?.focus();
  }, [failed, targetId]);

  const commit = (symbol: string, where: "target" | "new-chart"): void => {
    const into = where === "target" ? target : null;
    closeSymbolSearch();
    rememberSymbol(symbol);
    opener.open(symbol, into === null ? "new-chart" : "target");
    const off = link === "reconnecting" || link === "offline";
    // The user's own act: said at once, not after E17-D02 §11's 5 s region budget (`lastWrittenAt`).
    forget(COMMIT_KEY);
    announce("polite", commitSentence(symbol, into, off), COMMIT_KEY);
  };
  const onRootKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.key === "Escape" && !event.nativeEvent.isComposing) {
      event.preventDefault();
      closeSymbolSearch();
    }
    stopKeys(event, closeSymbolSearch); // §8: only a Global chord goes on to the window keymap
  };

  return (
    // A React ancestor of the portalled dialog, so its keydown is §8's root for every key in it.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- not a widget: no focus, no role
    <div onKeyDown={onRootKeyDown} style={{ display: "contents" }}>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) closeSymbolSearch();
        }}
        title={SEARCH_TITLE}
        aria-describedby={targetId}
        fallbackFocusRef={fallback}
      >
        <span id={targetId} className="cv-visually-hidden">
          {words.said}
        </span>
        <SymbolSearchInput
          value={query}
          onChange={setQuery}
          onSelect={(symbol) => commit(symbol, "target")}
          items={view.items}
          total={view.total}
          recentSymbols={view.recent}
          target={{ label: words.chip, armed: target?.armed === true }}
          {...(view.message === undefined ? {} : { message: view.message })}
          loading={view.loading}
          emptyMessage={empty(view.empty, index.reread)}
          visibleRows={rows}
          onKeyDown={(event, item) => {
            const chord = event.ctrlKey || event.altKey || event.metaKey;
            if (event.key !== "Enter" || !event.shiftKey || chord) return;
            event.preventDefault();
            if (item !== undefined && item.disabled !== true && !event.repeat)
              commit(item.id, "new-chart");
          }}
          aria-describedby={hintsId}
        />
        {view.loading ? (
          // Not CMP-038, whose own `role="status"` would be a second polite region (§9.2: one per surface): the
          // words are said through CMP-160's region, and this line is drawn for the eye only.
          <p style={LINE} aria-hidden="true">
            <Spinner size="sm" />
            {view.message}
          </p>
        ) : null}
        {view.total > view.items.length ? <p style={LINE}>{showing(view.total)}</p> : null}
        <p id={hintsId} style={LINE}>
          {keyHints(target?.pane ?? null).map(([keys, said], i) => (
            <span key={said}>
              {i === 0 ? null : "· "}
              <Kbd keys={keys} /> {said}
            </span>
          ))}
        </p>
      </Dialog>
    </div>
  );
}

/** §6.2's states in the list's place: the first run's lines, or CMP-026 `error` for a list that failed to load. */
function empty(state: SearchEmpty | null, retry: () => void): JSX.Element | null {
  if (state === null) return null;
  if (state.kind === "first-run")
    return (
      <div>
        {COPY.firstRun.map((line) => (
          <p key={line} style={LINE}>
            {line}
          </p>
        ))}
      </div>
    );
  const { failure } = state;
  const cause =
    failure?.cause === "http"
      ? COPY.answered(failure.status)
      : failure?.cause === "unavailable"
        ? COPY.unavailable
        : COPY.network;
  const instance = failure !== null && failure.cause !== "network" ? failure.instance : null;
  return (
    <EmptyState
      variant="error"
      live="assertive"
      title={COPY.failed}
      description={`${cause} ${COPY.nextTry(state.waitS)}`}
      actions={[{ label: COPY.retryNow, onClick: retry }]}
      {...(instance === null ? {} : { reference: instance })}
    />
  );
}
