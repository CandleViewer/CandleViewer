/**
 * The audit pages' polite lines (E42-D04 §12; the build plan's §5): each said once through the
 * shell's one announcer (E42-S01's BQ-8 ruling: no page live region), at most one per
 * `REGION_BUDGET_MS` behind any writer's last line, so a line never cuts another's (E17-D02 §11).
 * Nothing is said per row, tick, poll or keystroke: a caller names each line by a key of its own
 * occasion. Leaving the page drops what still waits and forgets what was said, so the next visit
 * says it again. The assertive voices are the components' own (the incident's `role="alert"`, the
 * export dialog's refusal) and CMP-033 says its own "Copied".
 */
import { useEffect, useState } from "react";
import { announce, forget, lastWrittenAt, REGION_BUDGET_MS } from "../../app-shell/announcer";

export interface PageVoice {
  /** Says `text` once, politely; a key said or waiting already says nothing more. */
  readonly say: (text: string, key: string) => void;
  /** The page is gone: nothing waiting is said and the keys said are forgotten. */
  readonly end: () => void;
}

interface Line {
  readonly text: string;
  readonly key: string;
}

export function createPageVoice(): PageVoice {
  let waiting: Line[] = [];
  const said = new Set<string>();
  let timer: ReturnType<typeof setTimeout> | null = null;
  /** The polite region's last write when the wait was armed: nobody wrote since, it is spent. */
  let armedFor: number | null = null;

  function next(): void {
    timer = null;
    const line = waiting[0];
    if (line === undefined) return;
    const last = lastWrittenAt("polite");
    const wait =
      last === armedFor ? 0 : Math.min(last + REGION_BUDGET_MS - Date.now(), REGION_BUDGET_MS);
    if (wait > 0) {
      armedFor = last;
      timer = setTimeout(next, wait);
      return;
    }
    waiting.shift();
    if (announce("polite", line.text, line.key)) said.add(line.key);
    next();
  }

  return {
    say: (text, key) => {
      if (said.has(key) || waiting.some((line) => line.key === key)) return;
      waiting.push({ text, key });
      if (timer === null) next();
    },
    end: () => {
      if (timer !== null) clearTimeout(timer);
      timer = null;
      waiting = [];
      for (const key of said) forget(key);
      said.clear();
    },
  };
}

/** The calling page's voice, ended when it unmounts. */
export function usePageVoice(): PageVoice["say"] {
  const [voice] = useState(createPageVoice);
  useEffect(() => () => voice.end(), [voice]);
  return voice.say;
}
