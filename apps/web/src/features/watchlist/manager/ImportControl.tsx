/**
 * SCR-101's "Import…" (E08-D07 D14, §4.3 Import and export, §4.4): CMP-067 FileDrop, a file picker whose zone also takes
 * a dropped file. One `.txt` or `.csv` file of plain UTF-8 text, at most 64 KB, read in the browser and never
 * uploaded (CMP-067 refuses a larger file or one that is not text: "This file is 2.1 MB. …", "This file isn't plain
 * text."; a file with no token: "This file has no symbols."). The same preview as a paste follows (§4.4's groups,
 * focus on its heading), then the targets: "Import into a new list "Breakouts"" (the file's name, made free) and "Add
 * to Majors" (T2 at 200 with the cap's words, D10). Without `workspaces:write` the control is T2 with the notice's
 * reason. Only the Trading symbols of the catalogue ever reach a request.
 */
import { useState, type JSX } from "react";
import { FileDrop, type FileDropAction } from "@candleviewer/ui";
import { COPY } from "../copy";
import type { InstrumentFacts, InstrumentSource } from "../instruments";
import { PreviewGroups, groupFacts, useTokenLookups } from "./BulkAdd";
import { MANAGER_COPY, MAX_FILE_BYTES } from "./copy";
import { freeName, groupSymbols, nameOfFile, tokensOf } from "./symbolText";

/** E08-D07 §4.4: `.txt` or `.csv`, `text/plain` or `text/csv`. */
const ACCEPT = ".txt,.csv,text/plain,text/csv";

export interface ImportControlProps {
  /** The list shown, its symbols and the names taken; `null` with no list (a new list is the one target). */
  readonly list: { readonly name: string; readonly symbols: readonly string[] } | null;
  readonly names: readonly string[];
  readonly facts: InstrumentFacts;
  readonly instruments: InstrumentSource;
  readonly writeReason: string | undefined;
  readonly reasonId: string | undefined;
  readonly onAddTo: (symbols: readonly string[]) => void;
  readonly onImportNew: (name: string, symbols: readonly string[]) => void;
}

export function ImportControl(props: ImportControlProps): JSX.Element {
  const { list, facts, writeReason } = props;
  const [file, setFile] = useState<{
    readonly name: string;
    readonly tokens: readonly string[];
  } | null>(null);
  const [error, setError] = useState<string | undefined>(undefined);
  useTokenLookups(props.instruments, facts, file?.tokens ?? []);

  const here =
    file === null || list === null
      ? null
      : groupSymbols(file.tokens, groupFacts(list.symbols, facts));
  const fresh = file === null ? null : groupSymbols(file.tokens, groupFacts([], facts));
  const shown = here ?? fresh;
  const actions: FileDropAction[] = [];
  if (file !== null && fresh !== null && fresh.add.length > 0) {
    const name = freeName(nameOfFile(file.name) || MANAGER_COPY.defaultName, props.names);
    actions.push({
      label: MANAGER_COPY.importInto(name),
      primary: list === null,
      onSelect: () => {
        setFile(null);
        props.onImportNew(name, fresh.add);
      },
    });
  }
  if (list !== null && here !== null) {
    const full = here.add.length === 0 && here.overCap.length > 0;
    if (here.add.length > 0 || full)
      actions.push({
        label: MANAGER_COPY.addTo(list.name),
        primary: true,
        ...(full ? { disabledReason: COPY.capFull } : {}),
        onSelect: () => {
          setFile(null);
          props.onAddTo(here.add);
        },
      });
  }

  return (
    <FileDrop
      label={MANAGER_COPY.importLabel}
      accept={ACCEPT}
      maxBytes={MAX_FILE_BYTES}
      oversizedMessage={MANAGER_COPY.oversized}
      notTextMessage={MANAGER_COPY.notText}
      // A new file's refusal is never preceded by the last one's words (A-5335-10).
      onPick={() => setError(undefined)}
      onText={(text, picked) => {
        const tokens = tokensOf(text);
        setError(tokens.length === 0 ? MANAGER_COPY.noSymbols : undefined);
        setFile(tokens.length === 0 ? null : { name: picked.name, tokens });
      }}
      {...(error === undefined ? {} : { error })}
      {...(writeReason === undefined
        ? {}
        : {
            disabledReason: writeReason,
            ...(props.reasonId === undefined ? {} : { disabledReasonId: props.reasonId }),
          })}
      {...(file === null || shown === null
        ? {}
        : {
            preview: {
              heading: MANAGER_COPY.previewOf(file.name),
              children: <PreviewGroups groups={shown} listName={list?.name ?? null} />,
              actions,
            },
          })}
    />
  );
}
