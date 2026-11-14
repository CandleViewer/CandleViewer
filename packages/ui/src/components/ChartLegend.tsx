import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type JSX,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Icon } from "../icons/Icon.js";
import { announcePolite } from "../theme/a11y.js";
import { IconButton } from "./IconButton.js";
import { Popover } from "./Popover.js";
import { NumericText } from "./Typography.js";
import { formatDisplayNumber } from "./internal/numberDisplay.js";
import { useFocusRing } from "./FocusRing.js";
import { cx } from "./internal/cx.js";
import { useGateNotice, useGatedAnnounce } from "./internal/disabledReason.js";

/** One of the eight indicator palette slots (E13-D04 §2.1); the CSS custom property is its kebab form. */
export type SlotToken = `color.indicator.palette.${1 | 2 | 3 | 4 | 5 | 6 | 7 | 8}`;

/** The swatch shape: the ladder tier, the non-colour carrier of a series' identity (E13-D04 §3). */
export type LegendMarker =
  | "line"
  | "thin"
  | "bold"
  | "dash"
  | "dash-dot"
  | "bar"
  | "bar-narrow"
  | "bar-outline"
  | "band"
  | "glyph";

export interface ChartLegendOutput {
  readonly name: string;
  readonly value: number | null;
  readonly marker: LegendMarker;
}

/** One series row (`15` CMP-199 Props); `value` is the cursor bar's, `null` before warm-up. */
export interface ChartLegendItem {
  readonly id: string;
  readonly label: string;
  readonly kind: string;
  readonly colorToken: SlotToken;
  readonly marker: LegendMarker;
  readonly value: number | null;
  readonly visible: boolean;
  readonly estimated?: boolean;
  /** The row's detail sentence, from a client-authored map (E13-D06 `d02.07.errored`), never a transport message. */
  readonly error?: string;
  readonly warmup?: { readonly needed: number };
  readonly beforeHistory?: { readonly startsAt: string };
  readonly outputs?: readonly ChartLegendOutput[];
  /** A ribbon's sub-rows (one hue, five tiers); the ribbon counts as one row for the overflow. */
  readonly children?: readonly ChartLegendItem[];
  readonly usedByRules?: boolean;
  readonly provisional?: boolean;
  readonly stale?: { readonly ageS: number; readonly lastGoodTs: string };
  readonly rebuilding?: boolean;
  readonly editing?: { readonly param: string };
}

export interface ChartLegendProps {
  readonly items: readonly ChartLegendItem[];
  readonly paneLabel: string;
  /** The initial disclosure; the chevron toggles it from there. */
  readonly collapsed: boolean;
  readonly onToggleVisible: (id: string, visible: boolean) => void;
  /** E13's remove-with-undo; the host owns the toast. Never arm-gated (`32` R5). */
  readonly onRemove?: (id: string) => void;
  /** The primary parameter's commit; the field's `Enter` is T2 under an enclosing CMP-079 notice. */
  readonly onQuickEdit?: (id: string, value: number) => void;
}

const DASH = "—";
const LABEL_MAX = 18;
const MIN_ROWS = 3;
/** How long a Remove's focus hand-off waits for the host to drop the row: the removal toast's 10 s (E13-D02 §12). */
const HANDOFF_MS = 10_000;
/** OQ-B: until the descriptor names its primary parameter. */
const PRIMARY_PARAM = "primary parameter (per descriptor)";
const PANE = "pane";

const slotVar = (token: SlotToken): string =>
  // The palette ships with E05-T01 (E13-D04 §2.3); until then the swatch falls back to a neutral ink.
  `var(--${token.replaceAll(".", "-")}, var(--color-text-secondary))`;

function Swatch(props: { readonly color: SlotToken; readonly marker: LegendMarker }): JSX.Element {
  const style = { "--cv-slot": slotVar(props.color) } as CSSProperties;
  return (
    <span
      aria-hidden="true"
      className="cv-chart-legend__swatch"
      data-marker={props.marker}
      style={style}
    />
  );
}

const num = (value: number | null): ReactNode =>
  value === null ? DASH : <NumericText value={value} format="price" size="sm" />;

const numText = (value: number | null): string =>
  value === null ? DASH : formatDisplayNumber(value, "price").text;

function valueTextOf(item: ChartLegendItem): string {
  if (!item.visible) return DASH;
  if (item.error !== undefined) return `error ${DASH}`;
  if (item.warmup !== undefined) return `${item.warmup.needed} more bars needed`;
  const base =
    item.outputs === undefined
      ? numText(item.value)
      : item.outputs.map((output) => numText(output.value)).join(" ");
  const frozen =
    item.stale !== undefined
      ? `Stale ${item.stale.ageS}s`
      : item.rebuilding === true
        ? "rebuilding…"
        : null;
  const word =
    frozen ??
    (item.provisional === true ? "provisional" : null);
  if (word === null) return base;
  return `${base} ${word}`;
}

function valueOf(item: ChartLegendItem): ReactNode {
  if (!item.visible) return DASH;
  if (item.error !== undefined) {
    return (
      <>
        <span className="cv-chart-legend__error-glyph">
          <Icon name="warning" size="sm" />
        </span>
        <span className="cv-chart-legend__word">error</span> {DASH}
      </>
    );
  }
  if (item.warmup !== undefined) return `${item.warmup.needed} more bars needed`;
  const base =
    item.outputs === undefined
      ? num(item.value)
      : item.outputs.map((output, i) => (
          <span key={output.name} className="cv-chart-legend__output">
            {i > 0 ? " " : null}
            <Swatch color={item.colorToken} marker={output.marker} />
            <span className="cv-visually-hidden">{output.name} </span>
            {num(output.value)}
          </span>
        ));
  // Stale and rebuilding keep the last value frozen in text.tertiary, with their word (E13-D02 §7.1).
  const frozen =
    item.stale !== undefined
      ? `Stale ${item.stale.ageS}s`
      : item.rebuilding === true
        ? "rebuilding…"
        : null;
  const word =
    frozen ??
    (item.provisional === true ? <span className="cv-chart-legend__word">provisional</span> : null);
  if (word === null) return base;
  return (
    <>
      {frozen === null ? base : <span data-frozen="">{base}</span>} {word}
    </>
  );
}

function detailOf(item: ChartLegendItem): string | undefined {
  if (item.error !== undefined) return item.error;
  if (item.stale !== undefined) return `last ${item.stale.lastGoodTs}`;
  if (item.beforeHistory !== undefined) {
    // The `14` §0.5 rule 3 stem (E13-D02 §7.1); its final wording is E16-D01 §4's.
    return `History starts ${item.beforeHistory.startsAt} — recording began then. ${item.label} starts there.`;
  }
  return undefined;
}

interface QuickEditProps {
  readonly item: ChartLegendItem;
  readonly onCommit: (value: number) => void;
  readonly onClose: (restoreFocus: boolean) => void;
}

/** KL-03: the compact field; `Enter` commits, `Esc` and blur revert. Under a gate notice `Enter` is T2. */
function QuickEdit({ item, onCommit, onClose }: QuickEditProps): JSX.Element {
  const notice = useGateNotice();
  const announceGated = useGatedAnnounce();
  const [text, setText] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [reasonShown, setReasonShown] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  const param = item.editing?.param ?? PRIMARY_PARAM;
  useEffect(() => field.current?.focus(), []);
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === "Escape") {
      // The field's Esc only reverts it; an enclosing popover or dialog must not close as well.
      event.preventDefault();
      event.stopPropagation();
      onClose(true);
      return;
    }
    if (event.key !== "Enter") return;
    event.preventDefault();
    if (notice !== null) {
      // E09-D09 §9.3: nothing commits; the reason re-shows under the row once, one polite announcement a press.
      setReasonShown(true);
      if (!event.repeat) announceGated(notice.reason);
      return;
    }
    const value = Number(text);
    if (text.trim() === "" || !Number.isFinite(value)) {
      setInvalid(true);
      return;
    }
    onCommit(value);
  };
  return (
    <span className="cv-chart-legend__edit" data-gated={notice === null ? undefined : ""}>
      <span className="cv-chart-legend__edit-label">
        {notice === null ? null : (
          <Icon name="lock" size="sm" decorative={false} label="Not available" />
        )}
        {param}
      </span>
      <input
        ref={field}
        type="number"
        className="cv-chart-legend__field"
        aria-label={`${param} for ${item.label}`}
        aria-invalid={invalid || undefined}
        aria-disabled={notice === null ? undefined : true}
        aria-describedby={notice?.noticeId}
        readOnly={notice !== null}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setInvalid(false);
        }}
        onKeyDown={onKeyDown}
        onBlur={() => onClose(false)}
      />
      {reasonShown && notice !== null ? (
        <span className="cv-chart-legend__detail">{notice.reason}</span>
      ) : null}
    </span>
  );
}

interface NavRow {
  readonly key: string;
  readonly controls: readonly string[];
}

const navId = (row: string, control: string): string => `${row}|${control}`;

/**
 * CMP-199 ChartLegend: the per-pane DOM overlay legend, the one home for per-series visibility toggles and cursor
 * values (E11-D02 D12, A-14). Props-fed: the host adapter feeds `items` from `Pane.legend` (PROPOSED); this
 * component holds no data subscription. One roving stop (KL-01): `↑/↓` rows (never wrapping), `←/→` a row's
 * controls (a ribbon's chevron collapses / expands), `Space` activates the focused control (the eye toggles visibility), `Enter` on the value
 * opens the quick-edit. Values are never announced; a toggle is, once, politely.
 */
export function ChartLegend({
  items,
  paneLabel,
  collapsed,
  onToggleVisible,
  onRemove,
  onQuickEdit,
}: ChartLegendProps): JSX.Element {
  const ring = useFocusRing();
  const notice = useGateNotice();
  const root = useRef<HTMLDivElement>(null);
  /**
   * A focus hand-off armed by Remove, keyed on the removed id: it survives re-renders that still hold the row (an
   * async host removal, value ticks) and lapses after `HANDOFF_MS`.
   */
  const pendingFocus = useRef<{
    readonly nav: string;
    readonly removedId: string;
    readonly row: Element | null;
    readonly expiresAt: number;
  } | null>(null);
  const pendingRestore = useRef<string | null>(null);
  const [isCollapsed, setCollapsed] = useState(collapsed);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [active, setActive] = useState(navId(PANE, "chevron"));
  const [focusWithin, setFocusWithin] = useState(false);
  const [maxRows, setMaxRows] = useState<number | null>(null);

  useEffect(() => setCollapsed(collapsed), [collapsed]);

  // Visible rows ≤ ⌊0.3 × pane height / row height⌋, never fewer than 3 (E11-D02 D12); the pane is the parent.
  useLayoutEffect(() => {
    const legend = root.current;
    const pane = legend?.parentElement;
    if (legend === null || pane === null || pane === undefined) return undefined;
    const measure = (): void => {
      const rowHeight =
        legend.querySelector<HTMLElement>(".cv-chart-legend__row:not(.cv-chart-legend__pane)")
          ?.offsetHeight ?? 0;
      const paneHeight = pane.clientHeight;
      setMaxRows(
        rowHeight > 0 && paneHeight > 0
          ? Math.max(MIN_ROWS, Math.floor((0.3 * paneHeight) / rowHeight))
          : null,
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(pane);
    return () => observer.disconnect();
  }, [isCollapsed, items.length]);

  const shown = maxRows === null || items.length <= maxRows ? items : items.slice(0, maxRows);
  const overflow = items.slice(shown.length);
  const hiddenCount = items.filter((item) => !item.visible).length;
  const byId = new Map<string, { item: ChartLegendItem; child: boolean }>();
  const rows: NavRow[] = [{ key: PANE, controls: ["chevron"] }];
  const editable = (item: ChartLegendItem, child: boolean): boolean =>
    !child && onQuickEdit !== undefined && (item.children?.length ?? 0) === 0;
  const controlsOf = (item: ChartLegendItem, child: boolean): string[] => [
    ...((item.children?.length ?? 0) > 0 ? ["chevron"] : []),
    ...(editable(item, child) && editingId !== item.id && item.editing === undefined
      ? ["value"]
      : []),
    "eye",
    ...(!child && onRemove !== undefined ? ["remove"] : []),
  ];
  if (!isCollapsed) {
    for (const item of shown) {
      byId.set(item.id, { item, child: false });
      rows.push({ key: item.id, controls: controlsOf(item, false) });
      if (!expanded.has(item.id)) continue;
      for (const sub of item.children ?? []) {
        byId.set(sub.id, { item: sub, child: true });
        rows.push({ key: sub.id, controls: controlsOf(sub, true) });
      }
    }
    if (overflow.length > 0) rows.push({ key: "more", controls: ["more"] });
  }
  const stops = new Set(rows.flatMap((row) => row.controls.map((c) => navId(row.key, c))));
  const tabStop = stops.has(active) ? active : navId(PANE, "chevron");
  const activeRow = tabStop.slice(0, tabStop.lastIndexOf("|"));

  const focusNav = (id: string): void => {
    setActive(id);
    root.current?.querySelectorAll<HTMLElement>("[data-nav]").forEach((node) => {
      if (node.getAttribute("data-nav") === id) node.focus();
    });
  };
  useEffect(() => {
    const restore = pendingRestore.current;
    if (restore !== null) {
      pendingRestore.current = null;
      focusNav(restore);
    }
    const pending = pendingFocus.current;
    if (pending === null) return;
    if (Date.now() > pending.expiresAt) {
      pendingFocus.current = null;
      return;
    }
    if (items.some((item) => item.id === pending.removedId)) return;
    pendingFocus.current = null;
    // Only focus the removal dropped is handed on: a user who has moved elsewhere keeps their place.
    const doc = root.current?.ownerDocument;
    const focused = doc?.activeElement ?? null;
    if (focused === null || focused === doc?.body || pending.row?.contains(focused) === true) {
      focusNav(stops.has(pending.nav) ? pending.nav : navId(PANE, "chevron"));
    }
  });

  const toggle = (item: ChartLegendItem): void => {
    onToggleVisible(item.id, !item.visible);
    announcePolite(`${item.label} ${item.visible ? "hidden" : "shown"}`);
  };
  const setRibbon = (id: string, open: boolean): void =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (open) next.add(id);
      else next.delete(id);
      return next;
    });
  const closeEdit = (id: string, restoreFocus: boolean): void => {
    setEditingId(null);
    if (restoreFocus) pendingRestore.current = navId(id, "value");
  };

  // On each control, not the group (a `group` is not interactive): events from the quick-edit field never arrive.
  const onKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
    const id = event.currentTarget.getAttribute("data-nav");
    if (id === null || event.altKey || event.ctrlKey || event.metaKey) return;
    const r = rows.findIndex((row) => id.startsWith(`${row.key}|`));
    const row = rows[r];
    if (row === undefined) return;
    const c = row.controls.indexOf(id.slice(row.key.length + 1));
    const control = row.controls[c];
    const entry = byId.get(row.key);
    const ribbonOpen = expanded.has(row.key);
    const move = (to: number, col: number): void => {
      const target = rows[to];
      if (target === undefined) return;
      const next = target.controls[Math.min(col, target.controls.length - 1)];
      if (next !== undefined) focusNav(navId(target.key, next));
    };
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      move(r + (event.key === "ArrowDown" ? 1 : -1), c);
    } else if (event.key === "ArrowRight") {
      if (control === "chevron" && entry !== undefined && !ribbonOpen) setRibbon(row.key, true);
      else move(r, c + 1);
    } else if (event.key === "ArrowLeft") {
      if (control === "chevron" && entry !== undefined && ribbonOpen) setRibbon(row.key, false);
      else if (c > 0) move(r, c - 1);
    } else {
      return;
    }
    event.preventDefault();
  };
  const onFocus = (event: FocusEvent<HTMLDivElement>): void => {
    const id = event.target.getAttribute("data-nav");
    if (id !== null) setActive(id);
    setFocusWithin(true);
  };
  const onBlur = (event: FocusEvent<HTMLDivElement>): void => {
    if (!event.currentTarget.contains(event.relatedTarget)) setFocusWithin(false);
  };

  const renderRow = (item: ChartLegendItem, child: boolean, popover: boolean): ReactNode => {
    const nav = (
      control: string,
    ): { "data-nav"?: string; tabIndex?: number; onKeyDown?: typeof onKeyDown } =>
      popover
        ? {}
        : {
            "data-nav": navId(item.id, control),
            tabIndex: tabStop === navId(item.id, control) ? 0 : -1,
            onKeyDown,
          };
    const ribbon = (item.children?.length ?? 0) > 0;
    const open = expanded.has(item.id);
    const name = item.estimated === true ? `${item.label} (estimated)` : item.label;
    const short = name.length > LABEL_MAX ? `${name.slice(0, LABEL_MAX - 1)}…` : name;
    const detail = detailOf(item);
    const editing = editable(item, child) && (editingId === item.id || item.editing !== undefined);
    const value = valueOf(item);
    const valText = valueTextOf(item);
    const editAction = `Edit ${item.editing?.param ?? PRIMARY_PARAM} for ${item.label}`;
    const valueButtonName = valText === DASH ? editAction : `${valText} — ${editAction}`;
    return [
      <li
        key={item.id}
        className="cv-chart-legend__row"
        data-child={child ? "" : undefined}
        data-hidden={item.visible ? undefined : ""}
        aria-current={!popover && focusWithin && activeRow === item.id ? true : undefined}
      >
        {ribbon ? (
          <IconButton
            icon={open ? "chevron-down" : "chevron-right"}
            label={`${open ? "Collapse" : "Expand"} ${item.label}`}
            variant="ghost"
            aria-expanded={open}
            onClick={() => setRibbon(item.id, !open)}
            {...nav("chevron")}
          />
        ) : null}
        <Swatch color={item.colorToken} marker={item.marker} />
        {item.provisional === true ? <Swatch color={item.colorToken} marker="dash" /> : null}
        <span className="cv-chart-legend__label" title={short === name ? undefined : name}>
          {short === name ? name : <span aria-hidden="true">{short}</span>}
          {short === name ? null : <span className="cv-visually-hidden">{name}</span>}
          {item.visible ? null : <span className="cv-visually-hidden"> hidden</span>}
          {item.usedByRules === true ? (
            <span className="cv-visually-hidden"> used by rules</span>
          ) : null}
        </span>
        {editing && onQuickEdit !== undefined ? (
          <QuickEdit
            item={item}
            onCommit={(next) => {
              onQuickEdit(item.id, next);
              closeEdit(item.id, true);
            }}
            onClose={(restore) => closeEdit(item.id, restore)}
          />
        ) : editable(item, child) ? (
          <button
            type="button"
            className={cx(
              "cv-chart-legend__value",
              "cv-chart-legend__value-button",
              ring.className,
            )}
            aria-label={valueButtonName}
            onClick={() => setEditingId(item.id)}
            {...nav("value")}
          >
            {value}
          </button>
        ) : (
          <span className="cv-chart-legend__value">{value}</span>
        )}
        <IconButton
          icon={item.visible ? "show" : "hide"}
          label={`${item.label} visible`}
          variant="ghost"
          pressed={item.visible}
          onClick={() => toggle(item)}
          {...nav("eye")}
        />
        {!child && onRemove !== undefined ? (
          <IconButton
            icon="delete"
            label={`Remove ${item.label}`}
            variant="ghost"
            {...(notice === null ? {} : { disabledReason: notice.reason })}
            onClick={(event) => {
              const at = rows.findIndex((entry) => entry.key === item.id);
              const near =
                rows[at + 1]?.key === "more" ? rows[at - 1] : (rows[at + 1] ?? rows[at - 1]);
              const control = near?.controls[near.controls.length - 1];
              pendingFocus.current = {
                nav:
                  near === undefined || control === undefined
                    ? navId(PANE, "chevron")
                    : navId(near.key, control),
                removedId: item.id,
                row: event.currentTarget.closest("li"),
                expiresAt: Date.now() + HANDOFF_MS,
              };
              onRemove(item.id);
            }}
            {...nav("remove")}
          />
        ) : null}
        {detail === undefined ? null : <span className="cv-chart-legend__detail">{detail}</span>}
      </li>,
      ...(open ? (item.children ?? []).map((sub) => renderRow(sub, true, popover)) : []),
    ];
  };

  const summary = isCollapsed || (items.length > 0 && hiddenCount === items.length);
  return (
    <div
      ref={root}
      role="group"
      aria-label={`${paneLabel} legend`}
      className="cv-chart-legend"
      data-cmp="CMP-199"
      onFocus={onFocus}
      onBlur={onBlur}
    >
      <ul className="cv-chart-legend__rows">
        <li
          className="cv-chart-legend__row cv-chart-legend__pane"
          aria-current={focusWithin && activeRow === PANE ? true : undefined}
        >
          <span className="cv-chart-legend__pane-label">{paneLabel}</span>
          {summary ? (
            <span className="cv-chart-legend__summary">{`${items.length} series · ${hiddenCount} hidden`}</span>
          ) : null}
          <IconButton
            icon={isCollapsed ? "chevron-right" : "chevron-down"}
            label={`${isCollapsed ? "Expand" : "Collapse"} ${paneLabel}`}
            variant="ghost"
            aria-expanded={!isCollapsed}
            onClick={() => setCollapsed(!isCollapsed)}
            data-nav={navId(PANE, "chevron")}
            tabIndex={tabStop === navId(PANE, "chevron") ? 0 : -1}
            onKeyDown={onKeyDown}
          />
        </li>
        {isCollapsed ? null : shown.map((item) => renderRow(item, false, false))}
        {!isCollapsed && overflow.length > 0 ? (
          <li
            className="cv-chart-legend__row"
            aria-current={focusWithin && activeRow === "more" ? true : undefined}
          >
            <Popover
              aria-label={`${overflow.length} more series`}
              anchor={
                <button
                  type="button"
                  className={cx("cv-chart-legend__more", ring.className)}
                  aria-label={`${overflow.length} more series`}
                  data-nav={navId("more", "more")}
                  tabIndex={tabStop === navId("more", "more") ? 0 : -1}
                  onKeyDown={onKeyDown}
                >
                  +{overflow.length} more
                </button>
              }
            >
              <ul className="cv-chart-legend__rows">
                {overflow.map((item) => renderRow(item, false, true))}
              </ul>
            </Popover>
          </li>
        ) : null}
      </ul>
    </div>
  );
}
