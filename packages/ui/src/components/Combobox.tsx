import {
  useEffect,
  useId,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Icon } from "../icons/Icon.js";
import { ReasonText } from "./internal/disabledReason.js";
import { useFieldControl } from "./internal/fieldContext.js";
import { focusFieldInput, useRefusalAnnounce } from "./internal/fieldParts.js";
import { useLayer, useLayerPortal } from "./internal/layers.js";
import { useAnchoredPosition } from "./internal/useAnchoredPosition.js";
import { Spinner } from "./Spinner.js";

export interface ComboboxOption {
  readonly value: string;
  readonly label: string;
  /** A gated option (T2): the lock, the label in `color.text.tertiary`, the reason its second line; never chosen. */
  readonly disabledReason?: string;
}

interface ComboboxBase {
  /** The text in the input, the combobox's value (APG list autocomplete); free text is the host's to validate. */
  readonly value: string;
  /** Typing passes the text; choosing an option passes its label and the option. */
  readonly onChange: (value: string, option?: ComboboxOption) => void;
  /** The host is loading the options: busy, the "Searching…" row. */
  readonly loading?: boolean;
  readonly placeholder?: string;
  /** Validity is a message (D02F conventions 23): the host decides when; the sentence is CMP-040's line. */
  readonly invalid?: boolean;
  readonly disabled?: boolean;
  /** The visible reason the control is denied (RBAC, environment, risk): T2. The list never opens. */
  readonly disabledReason?: string;
  /** Leading content in the well, as CMP-007's (a glyph is `aria-hidden` through `Icon`); a T2 lock comes first. */
  readonly prefix?: ReactNode;
  /** The name outside a CMP-040 FormField (whose label names the input and the list), passed to the input. */
  readonly "aria-label"?: string;
  readonly "aria-labelledby"?: string;
  /**
   * The rest after the last keystroke, ms, before the query settles: the search runs, the list opens and its count
   * is said. Default 500 (E05-D02's debounce); CMP-160 passes 300 (E08-D05 A-D05-6; #4703 G-row 3).
   */
  readonly settleMs?: number;
  /**
   * `false` opens the popup at once, without E05-D02's `motion.duration.fast` fade (E08-D05's hand-off, Table 4: none
   * animated; #4703 G-row 2). Default `true`; reduced motion is a cut either way.
   */
  readonly animated?: boolean;
  /**
   * Runs first on every key in the input (none while an IME composes), with the active option: a host binds its own
   * keys here (`Shift+Enter`, `Shift+F10`, the Menu key, its own `Esc`). `preventDefault()` skips the combobox's own
   * handling of that key, so every APG key stays the combobox's unless the host takes it (E08-D05 A-D05-6).
   */
  readonly onKeyDown?: (
    event: KeyboardEvent<HTMLInputElement>,
    active: ComboboxOption | undefined,
  ) => void;
}

/** Local options, filtered as the query settles; without `noResultsText` a no match keeps the list closed. */
interface LocalSource {
  readonly options: readonly ComboboxOption[];
  readonly asyncSearch?: never;
  readonly noResultsText?: string;
  readonly searchFailedText?: never;
}

/** The host's search, run once per settled query; it may abort on `signal`. Both sentences are the host's. */
interface AsyncSource {
  readonly asyncSearch: (query: string, signal: AbortSignal) => Promise<readonly ComboboxOption[]>;
  readonly options?: never;
  readonly noResultsText: string;
  readonly searchFailedText: string;
}

export type ComboboxProps = ComboboxBase & (LocalSource | AsyncSource);

/** A query settles this long after the last keystroke (D02F CMP-048): the search runs, the count is said. */
const SETTLE_MS = 500;
/** Page Up / Page Down's step when nothing is laid out to measure a page by: the list's ten-row cap. */
const FALLBACK_PAGE_ROWS = 10;
/** The keys a gated input refuses besides the editing ones: those that would open the list. */
const GATED_KEYS: ReadonlySet<string> = new Set(["ArrowDown", "ArrowUp"]);
/** The active option (-1: the text) and whether the pointer put it there, so each move keeps its scroll decision. */
type Active = { readonly index: number; readonly pointer: boolean };
const TEXT: Active = { index: -1, pointer: false };
/** The latest search's answer for `query`: pending until `done`. */
interface Result {
  readonly query: string;
  readonly options: readonly ComboboxOption[];
  readonly done: boolean;
  readonly failed: boolean;
}
const NO_RESULT: Result = { query: "", options: [], done: false, failed: false };

const counted = (n: number): string => `${String(n)} ${n === 1 ? "result" : "results"}`;
const reasonOf = (option: ComboboxOption): string | undefined =>
  option.disabledReason?.trim() || undefined;
const matchAt = (label: string, query: string): number =>
  query === "" ? -1 : label.toLowerCase().indexOf(query.toLowerCase());

/** The label with its matched part in `type.ui.body-strong`: weight, not colour. */
function marked(label: string, query: string): JSX.Element | string {
  const at = matchAt(label, query);
  if (at < 0) return label;
  const end = at + query.length;
  return (
    <>
      {label.slice(0, at)}
      <span className="cv-combobox__match">{label.slice(at, end)}</span>
      {label.slice(end)}
    </>
  );
}

/** One page for Page Up / Page Down: the rows that fit the list's visible height (by its first row), else the cap. */
function pageRows(list: HTMLElement | null): number {
  const view = list?.getBoundingClientRect().height ?? 0;
  const row = list?.querySelector(".cv-select__row")?.getBoundingClientRect().height ?? 0;
  return view > 0 && row > 0 ? Math.max(1, Math.floor(view / row)) : FALLBACK_PAGE_ROWS;
}

/**
 * CMP-048: the editable combobox with list autocomplete (APG). Focus stays in the input and
 * `aria-activedescendant` names the active option. Typing waits for the query to settle (`settleMs`, 500 ms after the
 * last keystroke by default): then local `options` filter, or `asyncSearch` runs with "Searching…" while it is in
 * flight, and the list opens; an older answer never overwrites a newer query's, an arrow opens the list at once, and
 * Page Up / Page Down move by the visible rows within an open list. The count, or
 * the host's sentence, is said politely once per settled query. The list portals and positions as CMP-017 does
 * and is a layer of the overlay stack: inside a CMP-043 Dialog it portals into the dialog's layer, and the first
 * `Esc` closes the list only.
 */
export function Combobox(props: ComboboxProps): JSX.Element {
  const { value, onChange, loading = false, invalid = false, asyncSearch } = props;
  const { settleMs = SETTLE_MS, animated = true } = props;
  const control = useFieldControl(props.disabled, props.disabledReason, invalid, undefined);
  const { reason } = control;
  const unavailable = reason.gated || reason.disabled;
  const ariaLabel = props["aria-label"];
  const ariaLabelledBy = props["aria-labelledby"];
  const labelledBy =
    ariaLabelledBy ?? (ariaLabel === undefined ? control.field?.labelId : undefined);
  const hasPrefix = props.prefix !== undefined && props.prefix !== null && props.prefix !== false;
  const listId = useId();
  const portalRoot = useLayerPortal();
  const well = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(TEXT);
  const [settled, setSettled] = useState(true);
  const [result, setResult] = useState(NO_RESULT);
  // A press on a T2 option says its reason; the count re-keys the node, so every press is said again.
  const [recall, setRecall] = useState<{ readonly text: string; readonly n: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const request = useRef<{ readonly query: string; readonly abort: AbortController } | null>(null);
  const search = useRef(asyncSearch);
  search.current = asyncSearch;

  const query = value.trim();
  // The settle searches the host's text as rendered: a host may normalise what was typed (upper-case, a cap).
  const latest = useRef(query);
  latest.current = query;
  const idle = asyncSearch !== undefined && query === "";
  const known = result.query === query && result.done;
  const busy = loading || (asyncSearch !== undefined && !idle && !known);
  const failed = !busy && known && result.failed;
  /** The results for the text: local options filtered, or the latest search's answer for it. */
  const results = (): readonly ComboboxOption[] =>
    busy || failed || idle
      ? []
      : (props.options?.filter((o) => query === "" || matchAt(o.label, query) >= 0) ??
        result.options);
  // Typing waits for the settle (D02F CMP-048): only then do local options filter and the list open.
  const shown = settled ? results() : [];
  const none = shown.length === 0 && query !== "";
  const sentence = failed ? props.searchFailedText : none ? props.noResultsText : undefined;
  const statusText = busy ? "Searching…" : sentence;
  const expanded =
    open && settled && !unavailable && (shown.length > 0 || statusText !== undefined);
  const current = expanded && active.index < shown.length ? active.index : -1;
  // Said once per settled query: the region empties on a keystroke and fills as the query settles.
  const said = !open || idle || !settled || busy ? undefined : (sentence ?? counted(shown.length));
  const optionId = (index: number): string => `${listId}-${String(index)}`;

  const run = (text: string): void => {
    const find = search.current;
    if (find === undefined || text === "" || request.current?.query === text) return;
    request.current?.abort.abort();
    const mine = { query: text, abort: new AbortController() };
    request.current = mine;
    setResult({ ...NO_RESULT, query: text });
    // Only the latest request may answer: a stale one is aborted, and its late answer ignored.
    const answer = (options: readonly ComboboxOption[], didFail: boolean): void => {
      if (request.current === mine)
        setResult({ query: text, options, done: true, failed: didFail });
    };
    find(text, mine.abort.signal).then(
      (options) => answer(options, false),
      () => answer([], true),
    );
  };
  const close = (): void => {
    clearTimeout(timer.current);
    setSettled(true);
    setOpen(false);
    setActive(TEXT);
    setRecall(null);
  };
  const edit = (text: string): void => {
    onChange(text);
    request.current?.abort.abort();
    request.current = null;
    close(); // a fresh query: no timer, no active option, nothing recalled; then it opens
    setSettled(false);
    setOpen(true);
    timer.current = setTimeout(() => {
      setSettled(true);
      run(latest.current);
    }, settleMs);
  };
  const choose = (index: number): void => {
    const option = shown[index];
    const why = option === undefined ? undefined : reasonOf(option);
    if (why !== undefined) setRecall((prev) => ({ text: why, n: (prev?.n ?? 0) + 1 }));
    else if (option !== undefined) {
      onChange(option.label, option);
      close();
    }
  };

  const handleKey = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.nativeEvent.isComposing) return;
    const prevented = event.defaultPrevented; // before the host's turn
    props.onKeyDown?.(event, current >= 0 ? shown[current] : undefined);
    const { key, altKey } = event;
    if (unavailable || event.defaultPrevented !== prevented) return; // gated, or the host took the key
    if (event.ctrlKey || event.metaKey || event.shiftKey) return; // chords are the host's
    if (key === "ArrowDown" || key === "ArrowUp") {
      event.preventDefault();
      if (altKey && key === "ArrowUp") return close();
      // An arrow opens at once: the query settles now, and a pending settle is dropped.
      clearTimeout(timer.current);
      setSettled(true);
      setOpen(true);
      run(query);
      if (altKey) return; // Alt+↓ opens without moving
      // ↓ from the text reaches the first option; ↑ on the first returns to the text; no wrap.
      const last = results().length - 1;
      const index = key === "ArrowDown" ? Math.min(current + 1, last) : current - 1;
      setActive({ index: Math.max(index, -1), pointer: false });
    } else if (
      (key === "PageDown" || key === "PageUp") &&
      expanded &&
      shown.length > 0 &&
      !altKey
    ) {
      // One visible page (E13-D02 D3, adopted by E08-D05 A-D05-6), within the list: no wrap, never back to the text.
      event.preventDefault();
      const page = pageRows(document.getElementById(listId));
      const down = Math.min(current + page, shown.length - 1);
      const up = current < 0 ? current : Math.max(current - page, 0);
      setActive({ index: key === "PageDown" ? down : up, pointer: false });
    } else if (key === "Enter" && current >= 0 && !altKey) {
      event.preventDefault(); // with none active, Enter is the host's
      choose(current);
    } else if (key === "Escape") {
      // The list is the topmost layer and this is its own handler: it stops here; a second Esc bubbles.
      if (expanded) {
        event.preventDefault();
        event.stopPropagation();
      }
      close(); // a list still waiting for its settle never opens
    }
  };

  // A key move scrolls the active row into view; a hover never moves the list under the pointer.
  useEffect(() => {
    if (current >= 0 && !active.pointer)
      document
        .getElementById(`${listId}-${String(current)}`)
        ?.closest(".cv-select__row")
        ?.scrollIntoView({ block: "nearest" });
  }, [active, current, listId]);
  useEffect(
    () => () => {
      clearTimeout(timer.current);
      request.current?.abort.abort();
      request.current = null; // a late answer then sets no state
    },
    [],
  );
  useAnchoredPosition({
    open: expanded,
    reference: well,
    floating: popup,
    side: "bottom",
    fit: true,
  });
  useLayer(expanded, { element: popup, modal: false, onEscape: close });
  const refusal = useRefusalAnnounce(reason, { onKeyDown: handleKey, onBlur: close }, GATED_KEYS);

  const list = (
    // A pointer surface: a press keeps focus in the input, which drives the list.
    <div
      ref={popup}
      role="presentation"
      className="cv-combobox__popup"
      data-animated={animated ? undefined : "false"}
      onMouseDown={(event) => event.preventDefault()}
    >
      <div
        id={listId}
        role="listbox"
        tabIndex={-1}
        className="cv-combobox__list"
        aria-label={ariaLabel}
        aria-labelledby={labelledBy}
        aria-busy={busy ? true : undefined}
      >
        {shown.map((option, index) => {
          const why = reasonOf(option);
          const whyId = `${optionId(index)}-why`;
          return (
            // CMP-009's option row: a presentational pointer target around the option and its reason line.
            <div
              key={option.value}
              role="presentation"
              className="cv-select__row"
              data-kind={why === undefined ? undefined : "locked"}
              data-lines={why === undefined ? undefined : 2}
              data-active={index === current ? "" : undefined}
              onMouseMove={() => {
                if (index !== current) setActive({ index, pointer: true });
              }}
              onClick={() => {
                setActive({ index, pointer: true });
                choose(index);
              }}
            >
              <span className="cv-select__check" />
              <div className="cv-select__body">
                <div
                  id={optionId(index)}
                  role="option"
                  className="cv-select__line"
                  aria-label={option.label} // the name is the label, never split at the bold match
                  aria-selected={index === current ? true : undefined}
                  aria-disabled={why === undefined ? undefined : true}
                  aria-describedby={why === undefined ? undefined : whyId}
                >
                  {why === undefined ? null : (
                    <span className="cv-select__optlock">
                      <Icon name="lock" />
                    </span>
                  )}
                  <span className="cv-select__label">{marked(option.label, query)}</span>
                </div>
                {why === undefined ? null : (
                  <div id={whyId} className="cv-select__reason" aria-hidden="true">
                    {why}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {/* A status row is not an option: it follows the list, and its words reach the live region. */}
      {statusText === undefined ? null : (
        <div className="cv-combobox__status">
          {busy ? <Spinner size="sm" /> : null}
          {failed ? (
            <span className="cv-field__glyph">
              <Icon name="danger" />
            </span>
          ) : null}
          <span>{statusText}</span>
        </div>
      )}
    </div>
  );

  return (
    <div className="cv-field-root" data-cmp="CMP-048">
      {/* The mouse handler only forwards a press to the input; the input is the keyboard and AT target. */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- see above: not a widget */}
      <div
        ref={well}
        className="cv-field"
        data-invalid={control.invalid ? "" : undefined}
        data-gated={reason.gated ? "" : undefined}
        data-disabled={reason.disabled ? "" : undefined}
        data-lead={reason.gated || hasPrefix ? "" : undefined}
        onMouseDown={(event) => focusFieldInput(event, inputRef)}
      >
        {reason.gated ? (
          <span className="cv-field__lead cv-field__lock">
            <Icon name="lock" decorative={false} label="Not available" />
          </span>
        ) : null}
        {hasPrefix ? <span className="cv-field__lead cv-field__affix">{props.prefix}</span> : null}
        <input
          ref={inputRef}
          id={control.field?.controlId}
          type="text"
          role="combobox"
          className="cv-field__input"
          value={value}
          placeholder={props.placeholder}
          autoComplete="off"
          disabled={reason.disabled}
          readOnly={reason.gated}
          aria-autocomplete="list"
          aria-expanded={expanded}
          aria-controls={expanded ? listId : undefined}
          aria-activedescendant={current >= 0 ? optionId(current) : undefined}
          aria-label={ariaLabel}
          aria-labelledby={ariaLabelledBy}
          aria-describedby={control.describe()}
          aria-invalid={control.invalid ? true : undefined}
          aria-required={control.required}
          aria-disabled={reason.ariaDisabled}
          onChange={(event) => edit(event.target.value)}
          {...refusal.handlers}
        />
      </div>
      {control.reasonFromField ? null : (
        <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      )}
      {refusal.status}
      {unavailable ? null : (
        <span className="cv-visually-hidden" role="status">
          {recall === null ? said : <span key={recall.n}>{recall.text}</span>}
        </span>
      )}
      {expanded && portalRoot !== null ? createPortal(list, portalRoot) : null}
    </div>
  );
}
