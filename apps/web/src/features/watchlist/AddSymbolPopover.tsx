/**
 * SCR-100's "+ Add symbol" (E08-D07 D36, §4.2 Adding): a non-modal CMP-017 popover titled with the list ("Add to
 * Majors"), holding CMP-160 ranked by E08-S09's module (the Trading listing; E08-D05 §4). `Enter` or a click adds the
 * active result at the end of the list and clears the input, so the popover stays for the next; a symbol already on
 * the list shows its outcome ("On Majors"), never T2, and choosing it adds nothing. A status line under the input shows
 * the last add or outcome, and each is said once, politely. At 200 symbols the input is T2 with the cap's words (D10).
 * `Esc`, a click outside or `Tab` out closes it; the adds of one opening change the live window once (the panel's).
 */
import { useId, useState, type JSX } from "react";
import { Button, Popover, SymbolSearchInput, type FuzzyListItem } from "@candleviewer/ui";
import { COPY as SEARCH_COPY } from "../symbol-search/copy";
import { rankSymbols, RESULT_CAP } from "../symbol-search/ranking";
import { rankedItem } from "../symbol-search/searchView";
import type { AddOutcome } from "./listEdits";
import { COPY } from "./copy";
import type { InstrumentFacts } from "./instruments";

/** E08-D05 §5's visible rows. */
const VISIBLE_ROWS = 8;

const STATUS = {
  margin: 0,
  paddingBlockStart: "var(--space-2)",
  color: "var(--color-text-secondary)",
} as const;

export interface AddSymbolPopoverProps {
  readonly listName: string;
  readonly listSymbols: readonly string[];
  readonly facts: InstrumentFacts;
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly onAdd: (symbol: string) => AddOutcome;
  /** Says one polite message in the app's region. */
  readonly say: (text: string) => void;
  /** T2 on the button (read-only, or the cap): the reason, and the host's node that shows it. */
  readonly reason?: { readonly text: string; readonly nodeId: string } | undefined;
}

export function AddSymbolPopover(props: AddSymbolPopoverProps): JSX.Element {
  const { listName, listSymbols, facts, open } = props;
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const statusId = useId();
  const onList = new Set(listSymbols);
  const result = rankSymbols(query, {
    phase: facts.snapshot.phase,
    entries: facts.snapshot.entries,
  });
  const rows = result.kind === "results" ? result.rows.slice(0, RESULT_CAP) : [];
  const items: FuzzyListItem[] = rows.map((row) => {
    const item = rankedItem(row);
    // On the list: its outcome, as a chip whose words join the option's name; never T2 (E08-D07 §6.6).
    return onList.has(item.id) ? { ...item, chip: { label: COPY.onList(listName) } } : item;
  });
  const none = result.kind === "none" ? SEARCH_COPY.noMatch(query.trim()) : undefined;
  const full = listSymbols.length >= 200 ? COPY.capFull : undefined;

  const choose = (symbol: string): void => {
    const outcome = props.onAdd(symbol);
    const text =
      outcome === "added"
        ? COPY.added(symbol, listName)
        : outcome === "on-list"
          ? COPY.alreadyOn(symbol, listName)
          : COPY.capFull;
    if (outcome === "added") setQuery("");
    setStatus(text);
    props.say(text);
  };

  const close = (next: boolean): void => {
    if (!next) {
      setQuery("");
      setStatus("");
    }
    props.onOpenChange(next);
  };

  const gated = props.reason;
  return (
    <Popover
      open={open}
      onOpenChange={close}
      aria-label={COPY.addTo(listName)}
      placement="above"
      anchor={
        <Button
          iconLeft="plus"
          variant="ghost"
          size="sm"
          {...(gated === undefined
            ? {}
            : { disabledReason: gated.text, disabledReasonId: gated.nodeId })}
        >
          {COPY.addSymbol}
        </Button>
      }
    >
      <SymbolSearchInput
        value={query}
        onChange={setQuery}
        items={items}
        total={result.kind === "results" ? result.total : 0}
        onSelect={(symbol) => choose(symbol)}
        loading={facts.snapshot.phase === "loading"}
        visibleRows={VISIBLE_ROWS}
        aria-label={COPY.addTo(listName)}
        aria-describedby={statusId}
        {...(none === undefined
          ? {}
          : {
              message: none,
              emptyMessage: <p style={STATUS}>{`${none} ${SEARCH_COPY.scope}`}</p>,
            })}
        {...(full === undefined ? {} : { disabledReason: full })}
      />
      <p id={statusId} style={STATUS}>
        {status}
      </p>
    </Popover>
  );
}
