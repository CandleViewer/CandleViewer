// The page of a client test: whether it is hidden, who watches that, and who hears it go away.
import type { Page } from "../../../../src/lib/ws/client/createWsClient";

export function fakePage(hidden = false) {
  let isHidden = hidden;
  const watchers = new Set<() => void>();
  const exits = new Set<() => void>();
  const page: Page = {
    hidden: () => isHidden,
    watch: (listener) => {
      watchers.add(listener);
      return () => void watchers.delete(listener);
    },
    onExit: (listener) => {
      exits.add(listener);
      return () => void exits.delete(listener);
    },
  };
  return {
    page,
    watchers,
    exits,
    show: (value: boolean) => {
      isHidden = value;
      for (const listener of [...watchers]) listener();
    },
    leave: () => {
      for (const listener of [...exits]) listener();
    },
  };
}
