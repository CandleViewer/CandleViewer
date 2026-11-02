// E22-S01 (#714) PR-B: SCR-053, the time & sales tape (D02 §2, §4, §11, §12). React renders the
// chrome only: the header with the pause button, the status row (chips, actions, the CP3 readout),
// the one `status` node and the `log` holding the `grid`. Rows are the grid writer's (C-70); the
// coarse state comes from the controller at most twice a second (D4-07, C-69). Behind
// `TAPE_ENABLED` (BQ-217); mounted only by the dev / Playwright harness until E15 docks it (BQ-206).
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
} from "react";
import { Button, Icon, Tag, Tooltip } from "@candleviewer/ui";
import { registerCommand } from "../../../keymap/KeymapHost";
import { locate as defaultLocate, type LocateRequest } from "../../../lib/state/chartLocate";
import type { WsClient } from "../../../lib/ws/api";
import { useWsState } from "../../../lib/ws/client/useWsState";
import type { TransportState } from "../../../lib/ws/state/types";
import { NEVER_WHALE, TapeAnnouncer, type Verbosity, type WhalePredicate } from "../announce";
import {
  COLUMNS,
  DISCONNECTED_PAUSE_REASON,
  GAPPED_CHIP,
  JUMP_TO_LIVE,
  LOAD_MISSED,
  LOADING,
  NAMES,
  NO_PRINTS_YET,
  OFFLINE_CHIP,
  PAUSE_LABEL,
  READOUT_NONE,
  READOUT_QUIET,
  SIDE_TOOLTIP,
  disconnectedStrip,
  emptyLine,
  pausedChip,
  pausedChipFull,
  panelTitle,
  readout,
  readoutShort,
  staleChip,
  viewAsNotice,
} from "../copy";
import { formatAge, formatSecond } from "../format";
import { fetchTradesPage, type FetchTrades } from "../model/history";
import { browserClock, type TapeClock } from "../model/tapeFeed";
import { useTapeSubscription } from "../useTapeSubscription";
import { COLUMN_COUNT, ROW_HEIGHT_PX, serverTier, type TierOf } from "./gridWriter";
import { INITIAL_CHROME, TapeController, type TapeChrome, type TapeEvent } from "./tapeController";

export interface TapePanelProps {
  /** A USDT perpetual; anything else subscribes to nothing (C-1.3). */
  readonly symbol: string;
  readonly paneId?: string | undefined;
  /** Defaults to the build-time flag (BQ-217). */
  readonly enabled?: boolean | undefined;
  /** Defaults to the app's active WS client. */
  readonly client?: Pick<WsClient, "consume" | "setPane"> | undefined;
  /** The ring's size (10 000 by default; E22-S05 owns the control, LIM:28). */
  readonly capacity?: number | undefined;
  readonly clock?: TapeClock | undefined;
  readonly wallNow?: (() => number) | undefined;
  readonly fetchTrades?: FetchTrades | undefined;
  /** Defaults to the app's WS transport (S10). */
  readonly transport?: TransportState | undefined;
  /** SCR-117's tape verbosity; `low` silences whales (AN-08). */
  readonly verbosity?: Verbosity | undefined;
  /** S21: a view-as context (no client source yet, #304 gap 13); its notice only (BQ-216). */
  readonly viewAs?: { readonly user: string } | null | undefined;
  /** BQ-210: E22-S02 injects tier 2 and the whale rule; until then tier 1 is the server's flag. */
  readonly tierOf?: TierOf | undefined;
  readonly isWhale?: WhalePredicate | undefined;
  /** BQ-212: the analytics seam; no sink is wired (D05 §7). */
  readonly onTapeEvent?: ((event: TapeEvent) => void) | undefined;
  readonly locate?: ((request: LocateRequest) => void) | undefined;
  /** Registers the Tape keymap commands (G-64); one panel at a time holds them. */
  readonly registerKeys?: boolean | undefined;
  /** The harness's and the tests' read of the running controller (counters only). */
  readonly onController?: ((controller: TapeController | null) => void) | undefined;
}

const ROOT: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  height: "100%",
  minWidth: "332px",
  background: "var(--color-surface-raised)",
  color: "var(--color-text-primary)",
  fontFamily: "var(--font-family-ui)",
};
const HEADER: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-2)",
  minHeight: "32px",
  padding: "var(--space-1) var(--space-3)",
  boxSizing: "border-box",
  borderBottom: "1px solid var(--color-border-default)",
};
const TITLE: CSSProperties = {
  margin: 0,
  flex: "1 1 auto",
  font: "inherit",
  fontWeight: "var(--font-weight-medium)",
};
const NOTICE: CSSProperties = {
  margin: 0,
  padding: "0 var(--space-3)",
  lineHeight: "24px",
  color: "var(--color-text-secondary)",
};
const STATUS_ROW: CSSProperties = {
  display: "flex",
  alignItems: "center",
  flexWrap: "wrap",
  gap: "var(--space-2)",
  minHeight: "28px",
  padding: "var(--space-1) var(--space-3)",
  boxSizing: "border-box",
  color: "var(--color-text-secondary)",
};
const READOUT: CSSProperties = {
  marginInlineStart: "auto",
  fontFamily: "var(--font-family-mono)",
  fontVariantNumeric: "tabular-nums",
};
const LOG: CSSProperties = { position: "relative", flex: "1 1 auto", minHeight: 0 };
const GRID: CSSProperties = {
  position: "absolute",
  inset: 0,
  overflowY: "auto",
  overflowX: "hidden",
  // the rows are rewritten in place at the top: the browser must never re-anchor the scroll
  overflowAnchor: "none",
  fontFamily: "var(--font-family-mono)",
  fontSize: "var(--font-size-xs)",
  fontVariantNumeric: "tabular-nums",
  // no `outline` here: with no row active the grid's own CMP-039 ring (`cv-focus-ring`) is the
  // visible focus (WCAG 2.4.7, FP-05); the controller hides it while an active cell draws its own
};
const HEAD_ROWGROUP: CSSProperties = {
  position: "sticky",
  top: 0,
  zIndex: 1,
  background: "var(--color-surface-raised)",
  borderBottom: "1px solid var(--color-border-default)",
};
const HEAD_ROW: CSSProperties = {
  display: "flex",
  height: "20px",
  alignItems: "center",
  gap: "var(--space-2)",
  padding: "0 var(--space-3)",
  color: "var(--color-text-tertiary)",
};
const HEAD_FLEX = ["0 0 12ch", "0 0 11ch", "0 0 8ch", "0 0 7ch", "1 1 auto"] as const;
const BODY: CSSProperties = { position: "relative" };
const WINDOW: CSSProperties = { position: "absolute", top: 0, left: 0, right: 0 };
const MESSAGE: CSSProperties = {
  position: "absolute",
  top: `${20 + ROW_HEIGHT_PX}px`,
  left: 0,
  right: 0,
  margin: 0,
  textAlign: "center",
  color: "var(--color-text-secondary)",
};
const SCRIM: CSSProperties = {
  position: "absolute",
  inset: 0,
  background: "var(--color-surface-app)",
  opacity: "var(--opacity-scrim)",
  pointerEvents: "none",
};
const STRIP: CSSProperties = {
  position: "absolute",
  top: 0,
  left: 0,
  right: 0,
  zIndex: 2,
  margin: 0,
  padding: "var(--space-1) var(--space-3)",
  background: "var(--color-surface-overlay)",
  color: "var(--color-text-primary)",
};
const PAUSE_BUTTON: CSSProperties = {
  position: "relative",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: "24px",
  height: "24px",
  padding: 0,
  border: "1px solid var(--color-border-default)",
  borderRadius: "var(--radius-sm)",
  background: "var(--color-surface-raised)",
  color: "var(--color-text-primary)",
  font: "inherit",
};
const BADGE: CSSProperties = {
  position: "absolute",
  right: "-4px",
  bottom: "-4px",
  display: "inline-flex",
};

/** CP3 (BQ-209): the readout's text for the chrome. */
export function readoutText(c: TapeChrome): string {
  if (c.phase === "loading") return LOADING;
  if (c.feed !== "live") return READOUT_NONE;
  if (c.phase === "empty" || c.ratePerSec === 0) return READOUT_QUIET;
  return c.paused ? readoutShort(c.ratePerSec) : readout(c.ratePerSec, c.perFrame);
}

const noopSubscribe = (): (() => void) => () => undefined;
const initialChrome = (): TapeChrome => INITIAL_CHROME;

export function TapePanel(props: TapePanelProps): JSX.Element {
  const { symbol, paneId = "tape", registerKeys = true } = props;
  const idBase = useId().replace(/[^A-Za-z0-9_-]/g, "");
  const reasonId = `${idBase}-pause-reason`;
  const noticeId = `${idBase}-notice`;
  const [clock] = useState<TapeClock>(() => props.clock ?? browserClock());
  const feed = useTapeSubscription(symbol, {
    paneId,
    enabled: props.enabled,
    client: props.client,
    capacity: props.capacity,
    clock,
  });
  const ws = useWsState();
  const transport = props.transport ?? ws.transport;
  const verbosity = props.verbosity ?? "normal";
  const grid = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const windowEl = useRef<HTMLDivElement>(null);
  const status = useRef<HTMLDivElement>(null);
  const [controller, setController] = useState<TapeController | null>(null);
  const latest = useRef(props);
  latest.current = props;
  const transportNow = useRef(transport);
  transportNow.current = transport;
  // BQ-211: the opt-in is hard off; one announcer per feed, reading the latest predicate
  const announcer = useMemo(
    () =>
      feed === null
        ? null
        : new TapeAnnouncer({
            isWhale: (ring, seq) => (latest.current.isWhale ?? NEVER_WHALE)(ring, seq),
          }),
    [feed],
  );

  useEffect(() => {
    if (feed === null || announcer === null) return undefined;
    const dom = {
      grid: grid.current,
      body: body.current,
      windowEl: windowEl.current,
      status: status.current,
    };
    if (dom.grid === null || dom.body === null || dom.windowEl === null || dom.status === null) {
      return undefined;
    }
    const pool = dom.windowEl;
    const gridEl = dom.grid;
    // the seams read the latest props at each call, so a prop change applies with no new feed
    const c = new TapeController({
      feed,
      clock,
      wallNow: () => (latest.current.wallNow ?? Date.now)(),
      fetchTrades: (query) => (latest.current.fetchTrades ?? fetchTradesPage)(query),
      announcer,
      tierOf: (flags) => (latest.current.tierOf ?? serverTier)(flags),
      onTapeEvent: (e) => latest.current.onTapeEvent?.(e),
      locate: (request) => (latest.current.locate ?? defaultLocate)(request),
      idBase,
    });
    c.setTransport(transportNow.current);
    c.setVerbosity(latest.current.verbosity ?? "normal");
    c.attach({ grid: dom.grid, body: dom.body, windowEl: dom.windowEl, status: dom.status });
    setController(c);
    latest.current.onController?.(c);
    return () => {
      latest.current.onController?.(null);
      c.dispose();
      pool.replaceChildren();
      // the next feed's writer starts clean: no cursor or count left from this one's rows
      gridEl.removeAttribute("aria-activedescendant");
      gridEl.setAttribute("aria-rowcount", "1");
      gridEl.style.removeProperty("outline");
      setController((current) => (current === c ? null : current));
    };
  }, [feed, clock, announcer, idBase]);

  useEffect(() => controller?.setTransport(transport), [controller, transport]);
  useEffect(() => controller?.setVerbosity(verbosity), [controller, verbosity]);

  // G-64: the Tape context. Every key but ←/→ goes through the app's keymap (so a rebind in
  // SCR-113 applies); a row key is valid only while the grid holds focus, so elsewhere in the
  // panel `Enter`, `Esc` and the arrows keep their native meaning.
  useEffect(() => {
    if (controller === null || !registerKeys) return undefined;
    const c = controller;
    const inGrid = (): boolean => c.gridFocused;
    const onRow = (): boolean => c.gridFocused && c.activeRow !== null;
    const offs = [
      registerCommand("tape.pause_toggle", () => void c.togglePause("key")),
      registerCommand("tape.jump_live", () => c.jumpLive()),
      registerCommand("tape.jump_oldest", () => c.jumpOldest()),
      registerCommand("tape.row_prev", () => void c.gridKey("ArrowUp"), inGrid),
      registerCommand("tape.row_next", () => void c.gridKey("ArrowDown"), inGrid),
      // Home / End only on a row: on the bare grid they keep scrolling the list (keymap.json)
      registerCommand("tape.cell_first", () => void c.gridKey("Home"), onRow),
      registerCommand("tape.cell_last", () => void c.gridKey("End"), onRow),
      registerCommand("tape.locate", () => void c.gridKey("Enter"), onRow),
      registerCommand(
        "tape.cancel",
        () => void c.gridKey("Escape"),
        () => c.canEscape,
      ),
    ];
    return () => offs.forEach((off) => off());
  }, [controller, registerKeys]);

  const chrome = useSyncExternalStore(
    controller?.subscribe ?? noopSubscribe,
    controller?.getSnapshot ?? initialChrome,
    controller?.getSnapshot ?? initialChrome,
  );

  // the APG grid's ←/→ between cells; the other keys are the keymap's (above)
  const onGridKey = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (controller === null || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (controller.gridKey(e.key)) e.preventDefault();
  };

  const gated = chrome.feed === "disconnected" && !chrome.hard;
  const pressPause = (): void => {
    controller?.togglePause("button");
  };

  return (
    <section
      aria-label={panelTitle(symbol)}
      data-cmp="SCR-053"
      data-keymap-context="Tape"
      style={ROOT}
    >
      <div style={HEADER}>
        <h2 style={TITLE}>{panelTitle(symbol)}</h2>
        <div role="toolbar" aria-label={NAMES.toolbar}>
          <Tooltip
            content={gated ? `${PAUSE_LABEL} · ${DISCONNECTED_PAUSE_REASON}` : PAUSE_LABEL}
            mode="echo"
          >
            <button
              type="button"
              aria-label={PAUSE_LABEL}
              aria-pressed={chrome.hard}
              aria-disabled={gated ? true : undefined}
              aria-describedby={gated ? reasonId : undefined}
              data-gated={gated ? "" : undefined}
              onClick={pressPause}
              style={{
                ...PAUSE_BUTTON,
                color: gated ? "var(--color-text-tertiary)" : PAUSE_BUTTON.color,
                background: chrome.hard ? "var(--color-surface-selected)" : PAUSE_BUTTON.background,
              }}
            >
              <span aria-hidden="true">❚❚</span>
              {gated ? (
                <span style={BADGE}>
                  <Icon name="lock" size="sm" decorative={false} label={NAMES.lock} />
                </span>
              ) : null}
            </button>
          </Tooltip>
          {/* rendering 2b: the reason node is in the DOM at mount, visually hidden (E09-D09 §9.2) */}
          <span id={reasonId} className="cv-visually-hidden">
            {gated ? DISCONNECTED_PAUSE_REASON : ""}
          </span>
        </div>
      </div>
      {props.viewAs ? (
        <p id={noticeId} style={NOTICE}>
          {viewAsNotice(props.viewAs.user)}
        </p>
      ) : null}
      <div style={STATUS_ROW} data-testid="tape-status-row">
        {chrome.feed === "disconnected" ? <Tag label={OFFLINE_CHIP} /> : null}
        {chrome.feed === "stale" ? (
          chrome.staleStrong ? (
            <Tag label={staleChip(chrome.staleSeconds)} variant="warning" />
          ) : (
            <Tag label={staleChip(chrome.staleSeconds)} />
          )
        ) : null}
        {chrome.paused ? (
          <span>
            <Tag
              label={chrome.notKept > 0 ? pausedChipFull(chrome.kept) : pausedChip(chrome.buffered)}
            />
            {chrome.scroll ? (
              <>
                {" · "}
                <Button size="sm" variant="ghost" onClick={() => controller?.jumpLive()}>
                  {JUMP_TO_LIVE}
                </Button>
              </>
            ) : null}
          </span>
        ) : null}
        {chrome.gapped ? <Tag label={GAPPED_CHIP} /> : null}
        {chrome.loadable ? (
          <Button
            size="sm"
            variant="ghost"
            loading={chrome.loading}
            onClick={() => controller?.loadMissed()}
          >
            {LOAD_MISSED}
          </Button>
        ) : null}
        <span aria-live="off" aria-label={NAMES.readout} role="note" style={READOUT}>
          {readoutText(chrome)}
        </span>
      </div>
      <div
        ref={status}
        role="status"
        aria-live="polite"
        aria-label={NAMES.status}
        className="cv-visually-hidden"
      />
      <div
        role="log"
        aria-live="off"
        aria-label={NAMES.log}
        style={{ ...LOG, opacity: chrome.feed === "stale" ? 0.85 : 1 }}
      >
        <div
          ref={grid}
          role="grid"
          tabIndex={0}
          aria-label={panelTitle(symbol)}
          aria-colcount={COLUMN_COUNT}
          aria-rowcount={1}
          aria-describedby={props.viewAs ? noticeId : undefined}
          data-testid="tape-grid"
          className="cv-focus-ring"
          style={GRID}
          onKeyDown={onGridKey}
          onFocus={(e) => {
            if (e.target === e.currentTarget) controller?.gridFocus();
          }}
          onBlur={(e) => {
            if (e.target === e.currentTarget) controller?.gridBlur();
          }}
          onScroll={(e) => controller?.scrolled(e.currentTarget.scrollTop)}
          onClick={(e) => {
            if (e.target instanceof Element) controller?.clickRow(e.target);
          }}
          onPointerEnter={() => controller?.pointerEnter()}
          onPointerMove={() => controller?.pointerMove()}
          onPointerLeave={() => controller?.pointerLeave()}
        >
          <div role="rowgroup" style={HEAD_ROWGROUP}>
            <div role="row" aria-rowindex={1} style={HEAD_ROW}>
              {COLUMNS.map((name, col) => (
                <div
                  key={name}
                  role="columnheader"
                  aria-label={name === "Side" ? SIDE_TOOLTIP : undefined}
                  style={{
                    flex: HEAD_FLEX[col],
                    textAlign: col === 0 || col === 4 ? "left" : "right",
                  }}
                >
                  {name}
                </div>
              ))}
            </div>
          </div>
          <div role="rowgroup" ref={body} style={BODY}>
            <div ref={windowEl} style={WINDOW} />
          </div>
        </div>
        {chrome.phase === "loading" ? <p style={MESSAGE}>{LOADING}</p> : null}
        {chrome.phase === "empty" ? (
          <p style={MESSAGE}>
            {chrome.emptyLastTsMs === null
              ? NO_PRINTS_YET
              : emptyLine(formatSecond(chrome.emptyLastTsMs))}
          </p>
        ) : null}
        {chrome.feed === "disconnected" ? (
          <>
            <div style={SCRIM} aria-hidden="true" />
            <p style={STRIP}>{disconnectedStrip(formatAge(chrome.lastPrintAgeMs))}</p>
          </>
        ) : null}
      </div>
    </section>
  );
}
