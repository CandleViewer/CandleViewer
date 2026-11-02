import { useEffect, useMemo, useState } from "react";
import { announce, forget } from "../app-shell/announcer";
import { resultsSentence, searchSettings, type SearchResult } from "./sections";

/** The count is said once typing stops: never one announcement per keystroke. */
export const SEARCH_SAY_MS = 600;
const SAID = "settings:search";

export function useSettingsSearch(): {
  readonly query: string;
  readonly setQuery: (q: string) => void;
  readonly results: readonly SearchResult[];
} {
  const [query, setQuery] = useState("");
  const results = useMemo(() => searchSettings(query), [query]);
  const active = query.trim() !== "";
  const sentence = resultsSentence(results);
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => {
      forget(SAID);
      announce("polite", sentence, SAID);
    }, SEARCH_SAY_MS);
    return () => clearTimeout(timer);
  }, [active, sentence]);
  return { query, setQuery, results };
}
