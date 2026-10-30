/**
 * SCR-041 Quick-switcher (E08-S09; E08-D05 §1, §7, §8, §9, §12.1, D-10): a non-modal CMP-017 popover on a chart
 * toolbar's CMP-219 trigger, CMP-160 over CMP-213 inside, for that one chart, on SCR-102's session, deck and words. The
 * chart toolbar (CMP-221) composes it once a chart is bound, and E12-S11 consumes its commit. The open key `/` lands
 * with E10-S02's dispatcher rule (A-D05-2); until then the trigger is the keyboard path, and `open` is the way in for
 * a host. The interval strip (CMP-220) is E12-D02 NC-10's: a slot here. The recording chips and Record are E16-S02's.
 */
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type JSX,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import {
  EmptyState,
  Popover,
  SymbolPicker,
  SymbolSearchInput,
  type FuzzyListItem,
} from "@candleviewer/ui";
import { COPY } from "./copy";
import type { InstrumentIndex } from "./instrumentIndex";
import { stopKeys } from "./keys";
import { rankSymbols, type Instrument } from "./ranking";
import {
  LINE,
  searchDeck,
  unmatchedOf,
  useFocusHome,
  useRested,
  useSaidAgain,
  useSymbolCheck,
} from "./searchDeck";
import {
  reportOpened,
  sayCommit,
  useDisconnected,
  useSearchReports,
  type Opened,
} from "./searchEvents";
import {
  useArrival,
  useHeldSnapshot,
  useRunningIndex,
  useSessionLookups,
  useSymbolSearch,
  type SymbolOpener,
  type SymbolTarget,
} from "./searchSession";
import { idleItem, rankedItem, waitS } from "./searchView";

/** The chart a switcher belongs to (D-10: SCR-041 targets its own chart). */
export type QuickSwitcherChart = SymbolTarget & {
  /** The current symbol is delisted (§7, reached through E11-D04's Switch symbol): B19's struck value. */
  readonly delisted?: boolean;
};

export interface QuickSwitcherProps {
  /** The chart the toolbar is bound to; `null` renders nothing, neither trigger nor placeholder. */
  readonly chart: QuickSwitcherChart | null;
  /**
   * The symbol-selection event E12-S11 consumes: this chart (`target`), or a new chart at this chart's interval
   * (`new-chart`). When `chart.armed`, the host MUST disarm the chart before it returns: the commit's sentence says
   * "Chart trading locked." (D-10, E30-D02). E12-D02 NC-10's strip commits an interval too, which will join this event.
   */
  readonly onCommit: SymbolOpener["open"];
  /** CMP-220's interval strip, between the list and the preview as B15 draws it (E12-D02 NC-10's). */
  readonly strip?: ReactNode;
  /** Controlled: `/` with this chart focused (#305), E11-D04's Switch symbol. Leave it out for the trigger's own. */
  readonly open?: boolean;
  /** Each request to open or close it: the trigger, `Esc`, a press outside, `Tab` out, a Global chord, a commit. */
  readonly onOpenChange?: (open: boolean) => void;
}

type Where = Parameters<SymbolOpener["open"]>[1];

const TITLE = "Change symbol and interval";
/** §7: the struck current value's description (B19). */
const delistedValue = (symbol: string): string =>
  `${symbol} is not trading on Bybit — choose another symbol.`;

/** A decimal without its trailing zeros ("100.00" → "100", "12.50" → "12.5"). */
const trimmed = (decimal: string): string =>
  decimal.includes(".") ? decimal.replace(/0+$/, "").replace(/\.$/, "") : decimal;

/** §7's preview: tick, lot, max leverage and funding from the list; 24 h turnover per D-8, held by no one here. */
function Preview({ instrument }: { readonly instrument: Instrument }): JSX.Element {
  const { tick_size: tick, qty_step: lot, max_leverage: leverage } = instrument;
  const minutes = instrument.funding_interval_minutes;
  const parts = [
    `tick ${tick}`,
    `lot ${lot}`,
    ...(leverage === undefined ? [] : [`max leverage ${trimmed(leverage)}×`]),
    ...(minutes === undefined ? [] : [`funding every ${String(minutes / 60)} h`]),
  ];
  return (
    <p style={LINE}>
      {parts.join(" · ")} · 24 h turnover <span aria-hidden="true">—</span>
      <span className="cv-visually-hidden">not available</span>
    </p>
  );
}

/** §5: 560 px, clamped to the window less 32 px (§7 Narrow); the surface's padding is CMP-017's. */
const BODY = {
  display: "grid",
  gap: "var(--space-stack-sm)",
  inlineSize: "min(560px, calc(100vw - 32px))",
} as const;
/** §8's key root draws no box: the trigger stays the toolbar's item. */
const CONTENTS = { display: "contents" } as const;

/** CMP-160 forwards no ref: its one combobox input, for §7's selected value, B19's strike and the focus home. */
const fieldIn = (root: HTMLElement | null): HTMLInputElement | null =>
  root?.querySelector<HTMLInputElement>("input[role='combobox']") ?? null;

interface BodyProps {
  readonly chart: QuickSwitcherChart;
  readonly index: InstrumentIndex;
  readonly open: boolean;
  readonly strip: ReactNode;
  readonly commit: (symbol: string, where: Where) => void;
  readonly close: () => void;
}

/** One opening: its query, active option, rest and symbol check start and end with it. */
function SwitcherBody({ chart, index, open, strip, commit, close }: BodyProps): JSX.Element {
  const live = useSyncExternalStore(index.subscribe, index.getSnapshot);
  const recent = useSymbolSearch((s) => s.recent);
  const unchecked = useSymbolSearch((s) => s.unchecked);
  const info = useSymbolSearch((s) => s.info);
  /** `null` until the first keystroke: the input holds the current symbol, selected, over the idle groups (§7). */
  const [query, setQuery] = useState<string | null>(null);
  const typed = query ?? "";
  const pristine = query === null;
  const snapshot = useHeldSnapshot(live, typed); // §6.2 Refreshing: a re-read's rows wait for the next key
  const remembered = [...recent, chart.symbol];
  useSessionLookups(index, live, remembered); // §3 row 2, once a session for both surfaces
  const arrival = useArrival(live); // the waits a snapshot names count from here
  const rows = useMemo(
    () => (document.documentElement.getAttribute("data-density") === "comfortable" ? 6 : 8),
    [],
  );
  const root = useRef<HTMLDivElement>(null);
  const [valueId, armedId] = [useId(), useId()];
  const struck = pristine && chart.delisted === true;

  useEffect(() => {
    const input = fieldIn(root.current);
    if (input === null) return;
    if (pristine) input.select();
    // B19: a delisted current value is struck (CMP-239's strike), through the CSSOM a strict CSP allows.
    input.style.textDecoration = struck ? "line-through" : "";
    input.style.color = struck ? "var(--color-data-confidence-delisted-text)" : "";
  }, [pristine, struck]);

  const result = useMemo(
    () => rankSymbols(typed, { ...snapshot, recent }),
    [typed, snapshot, recent],
  );
  const items = useMemo(() => {
    if (result.kind === "results") return result.rows.map(rankedItem);
    if (result.kind !== "idle") return [];
    return result.recent.map((row) => idleItem(row, snapshot.unlisted, unchecked));
  }, [result, snapshot.unlisted, unchecked]);
  const unmatched = unmatchedOf(typed, result, snapshot.unlisted, remembered);
  // A settled query that ranks nothing is checked, but not a remembered one the session found gone; closed, none is.
  const { check, checked } = useSymbolCheck(index, unmatched?.kind === "gone" ? "" : typed, open);
  const settled = useRested(typed); // a no-match names the query, so it is said once the query rests (CR-DD-01)
  // §9.2: a control that goes with its state (Check again, Retry now, Clear search) leaves no focus on the page.
  useFocusHome(() => fieldIn(root.current), open);
  const viewInfo =
    info === null
      ? undefined
      : (symbol: string): void => {
          close();
          info.open(symbol, { source: "scr-041" });
        };
  const deck =
    unmatched === null
      ? null
      : searchDeck(typed, unmatched, checked, settled, {
          clear: () => setQuery(""),
          checkAgain: () => check?.checkAgain(),
          info: viewInfo,
        });

  const failed = result.kind === "failed";
  const firstRun = result.kind === "idle" && items.length === 0;
  const { retryAt } = snapshot;
  const loading =
    result.kind !== "loading"
      ? null
      : retryAt === null
        ? COPY.loading
        : COPY.loadingRetry(waitS(retryAt, arrival));
  // §6.2: what `Enter` with no openable option says again: the state's heading.
  const heading =
    loading ?? (failed ? COPY.failed : firstRun ? COPY.firstRun[0] : (deck?.heading ?? null));
  // §9.2's one polite region (CMP-160's): the state's sentence; `""` keeps it quiet, `undefined` lets it say the count.
  // Load failed's alert speaks once; a no-match waits for its query to rest (the deck's `settled`, A11Y-D-04).
  const base = loading ?? (failed ? "" : deck === null ? undefined : deck.said);
  // What the user's own key asks to hear again (Enter's heading, Shift+Enter's reason): `useSaidAgain`.
  const { again, say } = useSaidAgain(typed, base, heading);
  const message = again?.text ?? base;

  const shown = loading !== null ? "catalogue_loading" : failed ? "catalogue_load_failed" : null;
  useSearchReports("scr-041", index, typed, open, shown ?? deck?.reason ?? null);
  const via = useRef<Opened["input"]>("key");
  /** A commit (§7) and its §12.1 report: the row's group, its 1-based rank there, a ranked row's tier, how it came. */
  const openIn = (symbol: string, where: Where): void => {
    const at = items.findIndex((item) => item.id === symbol);
    const ranked = result.kind === "results" ? result.rows : null;
    reportOpened("scr-041", {
      rank: at + 1,
      tier: ranked?.[at]?.tier ?? null,
      group: ranked === null ? "recent" : "results",
      input: via.current,
      action: where === "target" ? "open" : "new-chart",
    });
    commit(symbol, where);
  };

  let region: ReactNode = null;
  if (loading !== null)
    region = (
      <p style={LINE} aria-hidden="true">
        {loading}
      </p>
    );
  else if (failed)
    region = (
      <EmptyState
        variant="error"
        live="assertive"
        title={COPY.failed}
        actions={[{ label: COPY.retryNow, onClick: index.reread }]}
      />
    );
  else if (deck !== null)
    // Check again keeps its block, and the focus on it, while it runs: the check's line goes beside it (A11Y-D-01).
    region = (
      <>
        {deck.node}
        {deck.checking === null ? null : <p style={LINE}>{deck.checking}</p>}
      </>
    );
  else if (firstRun)
    region = (
      <div>
        {COPY.firstRun.map((line) => (
          <p key={line} style={LINE}>
            {line}
          </p>
        ))}
      </div>
    );

  // §7, B21, B23: the active row's preview, or the chart's own while the input still holds it; none while typing with
  // no row active (CR-D-01), and none for a row that can't be opened.
  const [active, setActive] = useState<FuzzyListItem | undefined>(undefined);
  let previewed = pristine ? chart.symbol : null;
  if (active !== undefined) previewed = active.disabled === true ? null : active.id;
  const preview = snapshot.entries.find((entry) => entry.symbol === previewed)?.instrument;
  const onKey = (event: KeyboardEvent<HTMLInputElement>, item?: FuzzyListItem): void => {
    if (event.key !== "Enter" || event.repeat || event.ctrlKey || event.altKey || event.metaKey)
      return;
    if (item === undefined) {
      if (heading !== null) say(heading); // inert, and the state's heading again
    } else if (event.shiftKey) {
      event.preventDefault(); // CMP-160's Enter commits to this chart, or says why not
      const why = item.reason?.trim() ?? "";
      if (item.disabled !== true) openIn(item.id, "new-chart");
      else if (why !== "") say(why); // §6.4: reached, never chosen, and it says why, as Enter does
    }
  };
  // The armed line is part of the input's description, so the lock is heard before the switch (D-10, CR-D-05).
  const described = [struck ? valueId : "", chart.armed ? armedId : ""].filter(Boolean).join(" ");

  return (
    // The body: §7's column, and how the last act came in (§12.1's `input`).
    <div
      ref={root}
      style={BODY}
      onKeyDownCapture={() => {
        via.current = "key";
      }}
      onPointerDownCapture={() => {
        via.current = "pointer";
      }}
    >
      <SymbolSearchInput
        value={query ?? chart.symbol}
        onChange={setQuery}
        onSelect={(symbol) => openIn(symbol, "target")}
        items={items}
        total={result.kind === "results" ? result.total : items.length}
        target={{
          label: `${chart.pane} · ${chart.symbol} ${chart.interval}`,
          armed: chart.armed,
        }}
        {...(message === undefined ? {} : { message })}
        {...(again === null ? {} : { messageKey: again.n })}
        emptyMessage={region}
        visibleRows={rows}
        onKeyDown={onKey}
        onActiveChange={setActive}
        {...(described === "" ? {} : { "aria-describedby": described })}
      />
      {struck ? (
        <p id={valueId} style={LINE}>
          {delistedValue(chart.symbol)}
        </p>
      ) : null}
      {strip}
      {preview === undefined ? null : <Preview instrument={preview} />}
      {chart.armed ? (
        <p id={armedId} style={LINE}>
          {COPY.armed(chart.pane)}
        </p>
      ) : null}
    </div>
  );
}

/**
 * SCR-041 on its chart's CMP-219, once a chart is bound and the shell's index runs: absent before, never a placeholder.
 * The index runs once `/me` has answered and a workspace has bound its opener (E12-S11 binds one with the chart); a
 * held index is not a running one (CR-CD-01).
 */
export function QuickSwitcher({ chart, ...rest }: QuickSwitcherProps): JSX.Element | null {
  const index = useRunningIndex();
  if (chart === null || index === null) return null;
  return <BoundSwitcher chart={chart} index={index} {...rest} />;
}

type Bound = Omit<QuickSwitcherProps, "chart"> & {
  readonly chart: QuickSwitcherChart;
  readonly index: InstrumentIndex;
};

function BoundSwitcher({ chart, index, onCommit, strip, ...control }: Bound): JSX.Element {
  const [held, setHeld] = useState(false);
  const open = control.open ?? held;
  const setOpen = (next: boolean): void => {
    setHeld(next);
    control.onOpenChange?.(next);
  };
  // Each opening mounts a fresh body, however it came: `Esc` restores the symbol, and nothing typed is kept (§7).
  const [opening, setOpening] = useState({ open, n: 0 });
  if (opening.open !== open) setOpening({ open, n: open ? opening.n + 1 : opening.n });
  const lost = useDisconnected();
  const commit = (symbol: string, where: Where): void => {
    setOpen(false); // CMP-017 hands focus back to the trigger
    onCommit(symbol, where);
    sayCommit(symbol, where === "target" ? chart : null, lost); // Recent remembers it; the shell says it
  };
  return (
    // §8's root: a React ancestor of the portalled popover, its surface and heading too, so every key pressed in it
    // stops here but a Global chord, which closes it and goes on (A11Y-D-03). The trigger keeps its own keys.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- not a widget: no focus, no role
    <div
      style={CONTENTS}
      onKeyDown={(event) => {
        const node = event.target instanceof Node ? event.target : null;
        if (!event.currentTarget.contains(node)) stopKeys(event, () => setOpen(false));
      }}
    >
      <Popover
        open={open}
        onOpenChange={setOpen}
        aria-label={`${TITLE}, ${chart.pane}`}
        heading={TITLE}
        anchor={
          <SymbolPicker
            value={chart.symbol}
            interval={chart.intervalWords}
            delisted={chart.delisted === true}
            onOpen={() => undefined} // CMP-017's toggle opens and closes it, after this
          />
        }
      >
        <SwitcherBody
          key={opening.n}
          chart={chart}
          index={index}
          open={open}
          strip={strip}
          commit={commit}
          close={() => setOpen(false)}
        />
      </Popover>
    </div>
  );
}
