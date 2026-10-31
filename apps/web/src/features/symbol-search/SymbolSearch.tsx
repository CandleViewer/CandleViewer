/**
 * SCR-102 Symbol search (E08-S09; E08-D05 §6, §8, §9.2, D-10, D-11): CMP-043 over CMP-160 and CMP-213, opened from
 * the TopBar's symbol trigger once a workspace has registered its opener. The shell keeps the TopBar, the banner slot,
 * the StatusBar and its live regions out of the inert page and the scrim (AppShell); a press there, or on the open
 * trigger, closes it without commit. Under the list, §6.4's detail bar with the active option's `⋯` (§6.3's CMP-041
 * menu, also on `Shift+F10`, the Menu key and a right-click), then the footer: its key hints or the catalogue's notice.
 */
import {
  useEffect,
  useId,
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
  Button,
  Dialog,
  EmptyState,
  Icon,
  IconButton,
  Kbd,
  Menu,
  RbacGate,
  Spinner,
  SymbolPicker,
  SymbolSearchInput,
  formatRbacReason,
  type EmptyStateAction,
  type FuzzyListItem,
  type MenuAnchor,
  type MenuItem,
} from "@candleviewer/ui";
import { getMeClaims } from "../../lib/auth/meCache";
import { registerCommand } from "../../keymap/KeymapHost";
import { COLUMNS, COPY, SEARCH_TITLE, keyHints, refreshAnswered, targetWords } from "./copy";
import { requestRefresh, type InstrumentIndex, type RefreshAnswer } from "./instrumentIndex";
import { stopKeys } from "./keys";
import { RESULT_CAP } from "./ranking";
import {
  LINE,
  searchDeck,
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
  canOpenSymbolSearch,
  closeSymbolSearch,
  forgetSymbol,
  openSymbolSearch,
  useArrival,
  useHeldSnapshot,
  useSessionLookups,
  useSymbolSearch,
  type SymbolOpener,
  type SymbolTarget,
} from "./searchSession";
import { placeOf, searchView, type SearchEmpty } from "./searchView";

/** The trigger's id: its own press toggles, so the TopBar-press close leaves it alone. */
export const SYMBOL_TRIGGER_ID = "cv-symbol-trigger";
/** §5's footer line ("Showing 50 of 213 results — keep typing to narrow"). */
const showing = (total: number): string =>
  `Showing ${String(RESULT_CAP)} of ${String(total)} results — keep typing to narrow`;
const HOUR_MS = 3_600_000;
/**
 * §6.2 Refresh answered: the job poll would end after 2 + 4 + 8 + 16 + 30 s; with no poll yet (E08-S01's route), the
 * answer's notice ends there too, if the list has not arrived first.
 */
const NOTICE_MS = 60_000;
/** The stale notice's line: its two actions and a T2 reason wrap at 200 % rather than overflow. */
const WRAPPED: CSSProperties = { ...LINE, flexWrap: "wrap" };
const BAR: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-inset-sm)",
  minBlockSize: "var(--size-row-height)",
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
 * Mounted once in the shell: SCR-102, while the index runs and a workspace can take a commit. `mainRef` is the shell's
 * `main`, where focus goes when neither the trigger nor the target panel is left to take it (§9.2).
 */
export function SymbolSearchHost({
  mainRef,
}: {
  readonly mainRef: RefObject<HTMLElement | null>;
}): JSX.Element | null {
  const index = useSymbolSearch((s) => s.index);
  const opener = useSymbolSearch((s) => s.opener);
  const open = useSymbolSearch((s) => s.open);
  const opened = useSymbolSearch((s) => s.opened);
  // `/` (A-D05-2): SCR-102 from anywhere but a text field. A focused chart's SCR-041 (E08-D05 D-1) is #451's port.
  useEffect(
    () => registerCommand("global.symbol_search", openSymbolSearch, canOpenSymbolSearch),
    [],
  );
  if (index === null || opener === null) return null;
  return (
    <SymbolSearchDialog key={opened} index={index} opener={opener} open={open} mainRef={mainRef} />
  );
}

interface DialogProps {
  readonly index: InstrumentIndex;
  readonly opener: SymbolOpener;
  readonly open: boolean;
  readonly mainRef: RefObject<HTMLElement | null>;
}

function SymbolSearchDialog({ index, opener, open, mainRef }: DialogProps): JSX.Element {
  const live = useSyncExternalStore(index.subscribe, index.getSnapshot);
  const recent = useSymbolSearch((s) => s.recent);
  const unchecked = useSymbolSearch((s) => s.unchecked);
  const info = useSymbolSearch((s) => s.info);
  const lost = useDisconnected();
  const [query, setQuery] = useState("");
  const arrival = useArrival(live); // the waits and ages a snapshot names count from here
  const snapshot = useHeldSnapshot(live, query);
  const rows = useMemo(() => {
    const density = document.documentElement.getAttribute("data-density");
    return visibleRows(window.innerHeight, density === "comfortable");
  }, []);
  const [targetId, hintsId, staleId, armedId] = [useId(), useId(), useId(), useId()];
  const { target } = opener;
  const words = targetWords(target);
  const remembered = target === null ? recent : [...recent, target.symbol];
  useSessionLookups(index, live, open ? remembered : []);
  const view = searchView(query, snapshot, recent, arrival, { remembered, unchecked });

  // A settled query that ranks nothing is checked, but not a remembered one the session found gone; closed, none is.
  const { check, checked } = useSymbolCheck(
    index,
    view.unmatched?.kind === "gone" ? "" : query,
    open,
  );
  const settled = useRested(query); // a no-match names the query, so it is said once the query rests (CR-DD-01)
  // §9.2: closing returns focus to the trigger, else the target panel, else the shell's `main`, never to the page.
  // Read when the dialog closes or unmounts, so a pane unbound or a workspace gone while it is open is seen.
  const fallback = useMemo<RefObject<HTMLElement | null>>(
    () => ({
      get current() {
        const panel = opener.panel?.current ?? null;
        return panel?.isConnected === true ? panel : mainRef.current;
      },
    }),
    [opener, mainRef],
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

  const card = (): Element | null | undefined =>
    document.getElementById(targetId)?.closest('[role="dialog"]');
  useFocusHome(() => card()?.querySelector<HTMLElement>('[role="combobox"]'), open);
  const viewInfo = (symbol: string): void => {
    closeSymbolSearch();
    info?.open(symbol, { source: "scr-102" });
  };
  const deck =
    view.unmatched === null
      ? null
      : searchDeck(query, view.unmatched, checked, settled, {
          clear: () => setQuery(""),
          checkAgain: () => check?.checkAgain(),
          info: info === null ? undefined : viewInfo,
        });
  const failed = view.empty?.kind === "failed";
  // §6.2: `Enter` with no openable option is inert and says the state's heading again.
  const heading = view.loading
    ? (view.message ?? null)
    : failed
      ? COPY.failed
      : view.empty?.kind === "first-run"
        ? COPY.firstRun[0]
        : (deck?.heading ?? null);
  // §9.2's one polite region (CMP-160's): the state's own sentence, or what the user's last act has it say again
  // (`Enter`'s heading, a T2 press's reason, a refresh's answer: `useSaidAgain`).
  const base = deck?.said ?? view.message;
  const { again, say } = useSaidAgain(query, base, heading);
  const message = again?.text ?? base;

  // §6.2's Refresh from Bybit, the Owner's (`instruments:write` in the session's permissions, never a role name; the
  // server enforces it): T2 `rbac.owner_only` for others, through CMP-079's vocabulary. One request at a time; its
  // answer takes the footer until the list next arrives or §6.2's poll would have ended, and the region says it once.
  const owner = getMeClaims().permissions.includes("instruments:write");
  const ownerOnly = formatRbacReason("rbac.owner_only", { verb: COPY.refreshVerb });
  const [refreshed, setRefreshed] = useState<{
    readonly answer: RefreshAnswer;
    readonly loadedAt: number | null;
  } | null>(null);
  if (refreshed !== null && refreshed.loadedAt !== live.loadedAt) setRefreshed(null);
  useEffect(() => {
    if (refreshed === null) return undefined;
    const timer = setTimeout(() => setRefreshed(null), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [refreshed]);
  const sending = useRef(false);
  const requestOnce = (): void => {
    if (refreshed?.answer.kind === "requested") {
      say(COPY.refreshRequested); // asked already: the list is on its way
      return;
    }
    if (sending.current) return;
    sending.current = true;
    void requestRefresh().then((answer) => {
      sending.current = false;
      setRefreshed({ answer, loadedAt: index.getSnapshot().loadedAt });
      say(refreshAnswered(answer));
    });
  };
  const refresh: EmptyStateAction = {
    label: COPY.refresh,
    onClick: requestOnce,
    variant: "secondary",
    ...(owner ? {} : { disabledReason: ownerOnly }),
  };

  // §12.1: what was searched and each state entered (while open), each option opened, and how the last act came in.
  useSearchReports(
    "scr-102",
    index,
    query,
    open,
    view.loading ? "catalogue_loading" : failed ? "catalogue_load_failed" : (deck?.reason ?? null),
  );
  const via = useRef<Opened["input"]>("key");
  const opened = (symbol: string, action: Opened["action"]): void =>
    reportOpened("scr-102", { ...placeOf(view, symbol), input: via.current, action });

  const commit = (symbol: string, where: "target" | "new-chart"): void => {
    const into = where === "target" ? target : null;
    opened(symbol, into === null ? "new-chart" : "open");
    closeSymbolSearch();
    opener.open(symbol, into === null ? "new-chart" : "target");
    sayCommit(symbol, into, lost);
  };

  // §6.3: the active option's menu, anchored to it (or at a right-click's point).
  const [active, setActive] = useState<FuzzyListItem | undefined>(undefined);
  const [menu, setMenu] = useState<{ item: FuzzyListItem; anchor: MenuAnchor } | null>(null);
  const actions = (item: FuzzyListItem): MenuItem[] => {
    const { id } = item;
    const run = (action: Opened["action"], then: () => void) => (): void => {
      opened(id, action);
      then();
    };
    const opens: MenuItem[] = [
      {
        id: "open",
        label: target === null ? COPY.openNew : COPY.openIn(target.pane),
        shortcut: ["Enter"],
        onSelect: () => commit(id, "target"),
      },
      ...(target === null
        ? []
        : [
            {
              id: "new",
              label: COPY.openNew,
              shortcut: ["Shift", "Enter"],
              onSelect: () => commit(id, "new-chart"),
            },
          ]),
    ];
    return [
      ...(item.disabled === true ? [] : opens),
      ...(info === null
        ? []
        : [{ id: "info", label: COPY.viewInfo, onSelect: run("info", () => viewInfo(id)) }]),
      ...(view.recent.some((row) => row.id === id)
        ? [{ id: "forget", label: COPY.forget, onSelect: run("forget", () => forgetSymbol(id)) }]
        : []),
    ];
  };
  const openMenu = (item: FuzzyListItem | undefined, at?: { x: number; y: number }): void => {
    const option = card()?.querySelector('[role="option"][aria-selected="true"]');
    const anchor = at === undefined ? option : { ...at, width: 0, height: 0 };
    if (item === undefined || anchor === null || anchor === undefined) return;
    if (actions(item).length > 0) setMenu({ item, anchor });
  };

  const onRootKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.key === "Escape" && !event.nativeEvent.isComposing) {
      event.preventDefault();
      closeSymbolSearch();
    }
    stopKeys(event, closeSymbolSearch); // §8: only a Global chord goes on to the window keymap
  };

  // §6.2's footer notices: they take the key hints' row, which stays the input's description.
  const age = Math.floor(
    ((live.cacheAgeS ?? 0) * 1000 + arrival - (live.loadedAt ?? arrival)) / HOUR_MS,
  );
  const notices = [
    lost && live.loadedAt !== null ? (
      <p key="link" style={LINE}>
        {COPY.disconnected(live.loadedAt)}
      </p>
    ) : null,
    live.staleSince === null ? null : (
      <p key="stale" style={WRAPPED}>
        <span style={{ display: "inline-flex", color: "var(--color-status-warning-strong)" }}>
          <Icon name="warning" />
        </span>
        <span id={staleId}>{COPY.stale(Math.max(1, age))}</span>
        <Button variant="secondary" onClick={index.reread}>
          {COPY.retry}
        </Button>
        {owner ? (
          <Button variant="secondary" onClick={requestOnce}>
            {COPY.refresh}
          </Button>
        ) : (
          // T2 in rendering 2a, as Load failed's (E08-D05 §6.2): CMP-001 keeps it focusable, `aria-disabled` and
          // described by its reason at mount; Enter, Space or a press changes nothing and says the reason once in the
          // surface's region (G-T2.3); the reason is drawn beside it for the eye, its description is the button's.
          <>
            <RbacGate allowed={false} reason="rbac.owner_only" fills={{ verb: COPY.refreshVerb }}>
              <Button
                variant="secondary"
                onClickCapture={() => say(ownerOnly)}
                onClick={requestOnce}
              >
                {COPY.refresh}
              </Button>
            </RbacGate>
            <span aria-hidden="true">{ownerOnly}</span>
          </>
        )}
      </p>
    ),
    refreshed === null ? null : (
      <p key="refresh" style={LINE}>
        {refreshAnswered(refreshed.answer)}
      </p>
    ),
    live.refreshing ? (
      <p key="refreshing" style={LINE}>
        {COPY.refreshing}
      </p>
    ) : null,
  ].filter((notice) => notice !== null);
  const line =
    (active === undefined ? deck?.checking : active.disabled === true ? active.reason : null) ??
    null;
  const armed = target?.armed === true ? COPY.armed(target.pane) : null;

  return (
    // A React ancestor of the portalled dialog, so its keydown is §8's root for every key in it.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- not a widget: no focus, no role
    <div
      onKeyDown={onRootKeyDown}
      onKeyDownCapture={() => {
        via.current = "key";
      }}
      onPointerDownCapture={() => {
        via.current = "pointer";
      }}
      // The context-menu event a `Shift+F10` or Menu key fires after it opened the menu.
      onContextMenu={(event) => {
        if (menu !== null) event.preventDefault();
      }}
      style={{ display: "contents" }}
    >
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) closeSymbolSearch();
        }}
        title={SEARCH_TITLE}
        aria-describedby={live.staleSince === null ? targetId : `${targetId} ${staleId}`}
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
          {...(message === undefined ? {} : { message })}
          {...(again === null ? {} : { messageKey: again.n })}
          loading={view.loading}
          emptyMessage={deck?.node ?? empty(view.empty, index.reread, refresh)}
          visibleRows={rows}
          columns={COLUMNS}
          onActiveChange={setActive}
          onContextMenu={(item, at) => openMenu(item, at)}
          onKeyDown={(event, item) => {
            if (event.ctrlKey || event.altKey || event.metaKey) return;
            if (event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey)) {
              event.preventDefault();
              openMenu(item);
            } else if (event.key !== "Enter" || event.repeat) {
              return;
            } else if (item === undefined) {
              if (heading !== null) say(heading);
            } else if (event.shiftKey) {
              event.preventDefault(); // CMP-160's Enter commits to the target, or says why not
              const why = item.reason?.trim() ?? "";
              if (item.disabled !== true) commit(item.id, "new-chart");
              else if (why !== "") say(why); // §6.4: reached, never chosen, and it says why, as Enter does
            }
          }}
          aria-describedby={armed === null ? hintsId : `${hintsId} ${armedId}`}
        />
        {view.loading ? (
          // Not CMP-038, whose own `role="status"` would be a second polite region (§9.2: one per surface): the
          // words are said through CMP-160's region, and this line is drawn for the eye only.
          <p style={LINE} aria-hidden="true">
            <Spinner size="sm" />
            {view.message}
          </p>
        ) : null}
        <div style={BAR}>
          <div style={{ flex: "1 1 auto", minInlineSize: 0 }}>
            {line === null ? null : <p style={LINE}>{line}</p>}
            {armed === null ? null : (
              <p id={armedId} style={LINE}>
                {armed}
              </p>
            )}
          </div>
          {active === undefined || actions(active).length === 0 ? null : (
            <IconButton
              icon="more-horizontal"
              label={COPY.actions(active.label)}
              variant="ghost"
              aria-haspopup="menu"
              aria-expanded={menu !== null}
              onClick={() => openMenu(active)}
            />
          )}
        </div>
        {view.total > view.items.length ? <p style={LINE}>{showing(view.total)}</p> : null}
        {notices}
        <p
          id={hintsId}
          style={LINE}
          className={notices.length > 0 ? "cv-visually-hidden" : undefined}
        >
          {keyHints(target?.pane ?? null).map(([keys, said], i) => (
            <span key={said}>
              {i === 0 ? null : "· "}
              <Kbd keys={keys} /> {said}
            </span>
          ))}
        </p>
        {menu === null ? null : (
          <Menu
            anchor={menu.anchor}
            open
            aria-label={COPY.actions(menu.item.label)}
            items={actions(menu.item)}
            onOpenChange={(next) => {
              if (!next) setMenu(null);
            }}
          />
        )}
      </Dialog>
    </div>
  );
}

/** §6.2's states in the list's place: the first run's lines, or CMP-026 `error` for a list that failed to load. */
function empty(
  state: SearchEmpty | null,
  retry: () => void,
  refresh: EmptyStateAction,
): JSX.Element | null {
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
      actions={[{ label: COPY.retryNow, onClick: retry }, refresh]}
      {...(instance === null ? {} : { reference: instance })}
    />
  );
}
