/**
 * Region (d) of SCR-141, the pinned symbols (E16-D03 §2 (d), §9 `SCR-141/pinned-list`; BQ-5, BQ-7): a list, not a
 * grid, of the symbols the editor holds exempt (else the storage report's pins), each with the pin glyph (named
 * "Pinned"), its size, "Exempt (pinned)" and its growth, words and glyph together (never colour alone, CR-05); a pin
 * the report does not list shows without size or growth. "Manage pin in Recorder" reaches SCR-140's row detail
 * (BQ-6's `openRowDetail`), shown only when that is registered; SCR-141 has no unpin control.
 */
import { useId, type JSX } from "react";
import { Heading, Icon, Text, useFocusRing } from "@candleviewer/ui";
import { RETENTION_DECK } from "./retentionCopy";
import type { StorageUsage, SymbolCode } from "./retentionModel";
import { growsText, sizeText } from "./retentionText";

export interface PinnedListProps {
  readonly storage: StorageUsage | null;
  /** The symbols the classification holds exempt (every source says pinned); absent, the report's pins. */
  readonly pinned?: readonly SymbolCode[] | undefined;
  /** Opens the symbol's row detail on SCR-140; absent, no link is drawn. */
  readonly onManage?: ((symbol: string) => void) | undefined;
}

export function PinnedList({ storage, pinned: held, onManage }: PinnedListProps): JSX.Element {
  const id = useId();
  const ring = useFocusRing();
  const listed = storage?.symbols ?? [];
  const usage = new Map(listed.map((s) => [s.symbol, s]));
  const pinned = (
    held ?? listed.flatMap((s) => (s.symbol === undefined || s.pinned !== true ? [] : [s.symbol]))
  ).map((symbol) => ({ symbol, usage: usage.get(symbol) }));
  return (
    <section aria-labelledby={`${id}-title`} aria-describedby={`${id}-help`}>
      <Heading id={`${id}-title`} level={3} variant="heading-sm">
        {RETENTION_DECK["retention.section.pinned"][0]}
      </Heading>
      <Text id={`${id}-help`} variant="caption" tone="secondary" as="p">
        {RETENTION_DECK["retention.pin.help"][0]}
      </Text>
      {pinned.length === 0 ? (
        <Text as="p">{RETENTION_DECK["retention.pin.none"][0]}</Text>
      ) : (
        <ul style={{ margin: 0, paddingInlineStart: 0, listStyle: "none" }}>
          {pinned.map((s) => (
            <li
              key={s.symbol}
              style={{
                display: "flex",
                flexWrap: "wrap",
                alignItems: "center",
                gap: "var(--space-inset-xs)",
              }}
            >
              <span style={{ color: "var(--color-text-secondary)", display: "inline-flex" }}>
                <Icon name="pin" decorative={false} label="Pinned" />
              </span>
              <Text id={`${id}-${s.symbol}`} variant="body-strong">
                {s.symbol}
              </Text>
              {s.usage === undefined ? null : <Text>· {sizeText(s.usage.used_bytes ?? 0)}</Text>}
              <Text tone="secondary">· {RETENTION_DECK["retention.exempt"][0]}</Text>
              {s.usage === undefined ? null : (
                <Text tone="secondary">· {growsText(s.usage.daily_growth_bytes ?? 0)}</Text>
              )}
              {onManage === undefined ? null : (
                <button
                  type="button"
                  className={`cv-link ${ring.className}`}
                  style={{ padding: 0, border: 0, background: "none" }}
                  aria-describedby={`${id}-${s.symbol}`}
                  onClick={() => onManage(s.symbol)}
                >
                  {RETENTION_DECK["retention.pin.manage"][0]}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
