import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { tabbables } from "./internal/tabbable.js";
import { useRoving } from "./internal/useRoving.js";

export interface TabItem {
  /** Must be unique within the strip (the roving focus and the selection are keyed by it). */
  readonly id: string;
  /** The visible label; it is the tab's accessible name. */
  readonly label: string;
  /** Icons=leading: a decorative CMP-019 glyph before the label. */
  readonly icon?: IconName;
  /** The host's sentence for a tab the session may not open: disabled-with-reason (T2). */
  readonly disabledReason?: string;
}

/** The tablist's accessible name is required (the host's, e.g. "Blotter"): one of the two, never neither. */
type TabsName =
  | { readonly "aria-label": string; readonly "aria-labelledby"?: string }
  | { readonly "aria-labelledby": string; readonly "aria-label"?: string };

export interface TabsBaseProps {
  readonly tabs: readonly TabItem[];
  /** The selected tab's id. */
  readonly value: string;
  readonly onChange: (id: string) => void;
  readonly orientation?: "horizontal" | "vertical";
  /** `manual` for a host whose switch re-shapes a form or costs a fetch: arrows move focus, Enter or Space selects. */
  readonly activation?: "automatic" | "manual";
  /** The content of the selected tab's panel; it mounts on selection and unmounts when another tab is selected. */
  readonly renderPanel: (id: string) => ReactNode;
  /** Emits `data-density` so `theme.css` re-points the tab height; absent = inherit. */
  readonly density?: "comfortable" | "compact";
}

export type TabsProps = TabsName & TabsBaseProps;

const reasonOf = (tab: TabItem): string | undefined => {
  const trimmed = tab.disabledReason?.trim();
  return trimmed === undefined || trimmed === "" ? undefined : trimmed;
};

/**
 * CMP-042: panel-local sections, the APG Tabs pattern with a roving tabindex. Arrows (wrapping), Home and End move
 * between tabs; automatic activation selects on arrival, manual waits for Enter or Space. A gated tab (T2) is
 * reachable and never selected: its reason line sits under the strip as its description, and Enter, Space or a
 * press on it re-announces the reason once. One panel per tab, `aria-labelledby` its tab; only the selected one is
 * mounted, and it takes `tabindex="0"` when it holds nothing focusable. A switch never moves focus off the tab, and
 * a panel that grabs focus as it mounts gives it back. The strip scrolls; it never wraps or hides a tab.
 */
export function Tabs({
  tabs,
  value,
  onChange,
  orientation = "horizontal",
  activation = "automatic",
  renderPanel,
  density,
  ...name
}: TabsProps): JSX.Element {
  const base = useId();
  const tabId = (index: number): string => `${base}-tab-${index}`;
  const panelId = (index: number): string => `${base}-panel-${index}`;
  // "One notice, many pointers": tabs gated for the same sentence share one reason line.
  const reasons = [...new Set(tabs.map(reasonOf).filter((r): r is string => r !== undefined))];
  const reasonId = (reason: string): string => `${base}-reason-${reasons.indexOf(reason)}`;
  // The refusal status: each refusal inserts a fresh node, so the same sentence is spoken again on the next press.
  const [spoken, setSpoken] = useState<{ readonly n: number; readonly text: string }>({
    n: 0,
    text: "",
  });
  const hush = (): void => setSpoken((s) => (s.text === "" ? s : { n: s.n, text: "" }));
  const panelRef = useRef<HTMLDivElement>(null);
  // The tab that asked for a switch, and the id it asked for: only that switch may hand focus back to it.
  const holdRef = useRef<{ readonly tab: HTMLElement; readonly id: string } | null>(null);
  const [panelEmpty, setPanelEmpty] = useState(false);

  const select = useCallback(
    (id: string): void => {
      if (id === value) return;
      // The tab that asked keeps focus through the switch, whatever the new panel does as it mounts.
      // A host that refuses the switch (never sets `value` to `id`) leaves a hold that no later change matches.
      holdRef.current =
        document.activeElement instanceof HTMLElement ? { tab: document.activeElement, id } : null;
      onChange(id);
    },
    [value, onChange],
  );
  const roving = useRoving({
    items: tabs.map((tab) => ({ value: tab.id, locked: reasonOf(tab) !== undefined })),
    checked: value,
    onSelect: select,
    selectOnFocus: activation === "automatic",
    groupRole: "tablist",
    orientation,
  });

  const refuse = (reason: string): void => setSpoken((s) => ({ n: s.n + 1, text: reason }));

  // A panel that took focus as it mounted (autoFocus in a layout pass, or a child's effect) gives it back.
  const giveBack = useCallback((): void => {
    const hold = holdRef.current;
    if (hold === null || hold.id !== value) return;
    const active = document.activeElement;
    if (active !== hold.tab && panelRef.current?.contains(active) === true) hold.tab.focus();
  }, [value]);
  useLayoutEffect(giveBack, [value, giveBack]);
  useEffect(() => {
    giveBack();
    holdRef.current = null;
  }, [value, giveBack]);

  // J10: a panel with nothing focusable is itself the next Tab stop, so its content can be reached and read.
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (panel === null) return undefined;
    const check = (): void => setPanelEmpty(tabbables(panel).length === 0);
    check();
    const observer = new MutationObserver(check);
    observer.observe(panel, { childList: true, subtree: true, attributes: true });
    return () => observer.disconnect();
  }, [value]);

  return (
    <div
      className="cv-tabs"
      data-cmp="CMP-042"
      data-orientation={orientation}
      data-density={density}
      onBlur={(event) => {
        // Focus leaving the component ends any hold: a refused switch's tab never pulls focus back later.
        if (!event.currentTarget.contains(event.relatedTarget)) holdRef.current = null;
      }}
    >
      <div className="cv-tabs__bar">
        <div
          {...name}
          role="tablist"
          className="cv-tabs__list"
          aria-orientation={orientation === "vertical" ? "vertical" : undefined}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget)) hush();
          }}
        >
          {tabs.map((tab, index) => {
            const reason = reasonOf(tab);
            const selected = tab.id === value;
            const item = roving.itemProps(tab.id);
            const onKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
              const chord = event.altKey || event.ctrlKey || event.metaKey;
              if (reason !== undefined && !chord && (event.key === "Enter" || event.key === " ")) {
                event.preventDefault();
                refuse(reason);
                return;
              }
              item.onKeyDown(event);
            };
            const onClick = (event: MouseEvent<HTMLElement>): void => {
              event.currentTarget.focus();
              if (reason !== undefined) refuse(reason);
              else select(tab.id);
            };
            return (
              <div
                key={tab.id}
                ref={item.ref}
                id={tabId(index)}
                role="tab"
                className="cv-tabs__tab"
                tabIndex={item.tabIndex}
                aria-selected={selected}
                aria-controls={panelId(index)}
                aria-disabled={reason === undefined ? undefined : true}
                aria-describedby={reason === undefined ? undefined : reasonId(reason)}
                data-selected={selected ? "" : undefined}
                data-gated={reason === undefined ? undefined : ""}
                onKeyDown={onKeyDown}
                onFocus={(event) => {
                  hush();
                  item.onFocus(event);
                }}
                onBlur={item.onBlur}
                onClick={onClick}
              >
                {reason === undefined ? null : (
                  <span className="cv-tabs__icon cv-tabs__lock">
                    <Icon name="lock" />
                  </span>
                )}
                {tab.icon === undefined ? null : (
                  <span className="cv-tabs__icon">
                    <Icon name={tab.icon} />
                  </span>
                )}
                <span className="cv-tabs__label">{tab.label}</span>
              </div>
            );
          })}
        </div>
        {reasons.map((reason) => (
          <p key={reason} id={reasonId(reason)} className="cv-tabs__reason">
            {reason}
          </p>
        ))}
        <span role="status" className="cv-visually-hidden">
          {spoken.text === "" ? null : <span key={spoken.n}>{spoken.text}</span>}
        </span>
      </div>
      {tabs.map((tab, index) => {
        const selected = tab.id === value;
        return (
          <div
            key={tab.id}
            ref={selected ? panelRef : undefined}
            id={panelId(index)}
            role="tabpanel"
            className="cv-tabs__panel"
            aria-labelledby={tabId(index)}
            hidden={!selected}
            tabIndex={selected && panelEmpty ? 0 : undefined}
          >
            {selected ? renderPanel(tab.id) : null}
          </div>
        );
      })}
    </div>
  );
}
