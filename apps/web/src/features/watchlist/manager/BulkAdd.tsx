/**
 * SCR-101's bulk add (E08-D07 D25, §4.3 Paste, §4.4, §6.5): "Paste symbols" opens a labelled text area and "Preview";
 * the preview groups the tokens (§4.4: what is added, then what is not and why, each as plain text), focus moving to
 * its heading, and "Add 12 symbols" adds the new Trading symbols at the end of the list, up to its cap (T2 at 200 with
 * the cap's words, D10). The same groups show for an imported file (`PreviewGroups`). A symbol of the right form that
 * the instrument index does not hold is looked up once (`GET /instruments/{symbol}`), at most 20 for a preview in all,
 * so a delisted one reads as delisted, not as unknown; until it answers, and past the 20, it reads "Not found". The
 * text is read up to the file's 64 KB; a text past it, or with no token, says so under the field instead of a preview.
 * Nothing pasted is sent but the symbols the catalogue holds.
 */
import { useEffect, useId, useState, type CSSProperties, type JSX } from "react";
import { Button, FormField, Heading, InlineError } from "@candleviewer/ui";
import { COPY } from "../copy";
import {
  PREVIEW_LOOKUPS,
  isDelisted,
  useListLookups,
  type InstrumentFacts,
  type InstrumentSource,
} from "../instruments";
import { MANAGER_COPY, MAX_FILE_BYTES } from "./copy";
import {
  groupSymbols,
  tokensOf,
  unknownTokens,
  type GroupFacts,
  type SymbolGroups,
} from "./symbolText";

const PANE: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "var(--space-2)",
  paddingBlock: "var(--space-2)",
};
const AREA: CSSProperties = {
  inlineSize: "100%",
  boxSizing: "border-box",
  minBlockSize: "5rem",
  padding: "var(--space-2)",
  font: "inherit",
  color: "var(--color-text-primary)",
  background: "var(--color-surface-app)",
  border: "1px solid var(--color-text-tertiary)",
  borderRadius: "var(--radius-control)",
};
const LIST: CSSProperties = { margin: 0, display: "grid", gap: "var(--space-1)" };
const TERM: CSSProperties = { color: "var(--color-text-secondary)" };
const DETAIL: CSSProperties = { margin: 0, overflowWrap: "anywhere" };

/** The facts a grouping reads: the list's symbols and the instrument index. */
export function groupFacts(onList: readonly string[], facts: InstrumentFacts): GroupFacts {
  const held = new Set(onList);
  const trading = new Set(facts.snapshot.entries.map((entry) => entry.symbol));
  return {
    onList: held,
    trading: (symbol) => trading.has(symbol),
    delisted: (symbol) => isDelisted(facts.bySymbol.get(symbol)),
  };
}

/**
 * Looks up, once, the tokens of the right form the index does not know (a delisted symbol reads as one): at most
 * `PREVIEW_LOOKUPS` for a preview, however many it holds.
 */
export function useTokenLookups(
  instruments: InstrumentSource,
  facts: InstrumentFacts,
  tokens: readonly string[],
): void {
  useListLookups(instruments, facts, unknownTokens(tokens, groupFacts([], facts)), PREVIEW_LOOKUPS);
}

/** §4.4's groups, each a term and its symbols as text; an empty group is left out. */
export function PreviewGroups({
  groups,
  listName,
}: {
  readonly groups: SymbolGroups;
  readonly listName: string | null;
}): JSX.Element {
  const rows: (readonly [string, readonly string[]])[] = [
    [MANAGER_COPY.toAdd, groups.add],
    [listName === null ? "" : MANAGER_COPY.alreadyOn(listName), groups.onList],
    [MANAGER_COPY.overCap(groups.overCap.length), groups.overCap],
    [MANAGER_COPY.notFound, groups.notFound],
    [MANAGER_COPY.delisted, groups.delisted],
    [MANAGER_COPY.invalid, groups.invalid],
  ];
  return (
    <dl style={LIST}>
      {rows
        .filter(([, symbols]) => symbols.length > 0)
        .map(([term, symbols]) => (
          <div key={term}>
            <dt style={TERM}>{term}</dt>
            <dd style={DETAIL}>{symbols.join(", ")}</dd>
          </div>
        ))}
    </dl>
  );
}

export interface PastePaneProps {
  readonly listName: string;
  readonly symbols: readonly string[];
  readonly facts: InstrumentFacts;
  readonly instruments: InstrumentSource;
  /** Adds the symbols; the host says the summary and moves focus to the first added row. */
  readonly onAdd: (symbols: readonly string[]) => void;
  /** Says a line once through the surface's announcer (a text that cannot be previewed). */
  readonly say: (text: string) => void;
}

export function PastePane(props: PastePaneProps): JSX.Element {
  const { listName, symbols, facts } = props;
  const fieldId = useId();
  const headingId = useId();
  const capId = useId();
  const problemId = useId();
  const [text, setText] = useState("");
  const [tokens, setTokens] = useState<readonly string[] | null>(null);
  /** Why the text has no preview: past 64 KB, or no token. */
  const [problem, setProblem] = useState<string | null>(null);
  const preview = (): void => {
    // Read up to the file's bound (C-5335-02) before a token is cut from it; a text with none says so (C-5335-12).
    const read = new TextEncoder().encode(text).length > MAX_FILE_BYTES ? null : tokensOf(text);
    const words =
      read === null
        ? MANAGER_COPY.pasteTooLong
        : read.length === 0
          ? MANAGER_COPY.pasteEmpty
          : null;
    setProblem(words);
    setTokens(words === null ? read : null);
    if (words !== null) props.say(words);
  };
  useTokenLookups(props.instruments, facts, tokens ?? []);
  const groups = tokens === null ? null : groupSymbols(tokens, groupFacts(symbols, facts));
  // After Preview, focus moves to the preview's heading (E08-D07 §6.5).
  useEffect(() => {
    if (tokens !== null) document.getElementById(headingId)?.focus();
  }, [tokens, headingId]);
  const full = groups !== null && groups.add.length === 0 && groups.overCap.length > 0;
  return (
    <div style={PANE}>
      <FormField label={MANAGER_COPY.pasteLabel} htmlFor={fieldId}>
        <textarea
          id={fieldId}
          style={AREA}
          rows={4}
          value={text}
          maxLength={MAX_FILE_BYTES}
          aria-invalid={problem === null ? undefined : true}
          aria-describedby={problem === null ? undefined : problemId}
          onChange={(event) => {
            setText(event.currentTarget.value);
            setTokens(null);
            setProblem(null);
          }}
        />
      </FormField>
      <span>
        <Button size="sm" onClick={preview}>
          {MANAGER_COPY.preview}
        </Button>
      </span>
      {problem === null ? null : (
        <div id={problemId}>
          <InlineError live="off" message={problem} />
        </div>
      )}
      {groups === null ? null : (
        <section aria-labelledby={headingId} style={PANE}>
          <Heading level={4} variant="heading-sm" id={headingId} tabIndex={-1}>
            {MANAGER_COPY.preview}
          </Heading>
          <PreviewGroups groups={groups} listName={listName} />
          {groups.add.length === 0 && !full ? null : (
            <span>
              <Button
                variant="primary"
                size="sm"
                {...(full ? { disabledReason: COPY.capFull, disabledReasonId: capId } : {})}
                onClick={() => props.onAdd(groups.add)}
              >
                {MANAGER_COPY.addN(groups.add.length)}
              </Button>{" "}
              {full ? (
                <span id={capId} style={TERM}>
                  {COPY.capFull}
                </span>
              ) : null}
            </span>
          )}
        </section>
      )}
    </div>
  );
}
