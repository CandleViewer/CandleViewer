/**
 * How SCR-101 opens (E08-D07 D24, §4.2, §4.3; #4702 PR (c)): at `?modal=watchlists` (R-110 `/watchlist` opens it), on
 * the list a path names, with what the path asked for. The intent is the page's, held in memory: the URL carries only
 * `?modal=watchlists`, so a reload or a deep link opens the manager on the list it shows, asking nothing more.
 */

/** The query parameter and value that open SCR-101 (`14` §0.1: modals are `?modal=<name>` query state). */
export const MODAL_PARAM = "modal";
export const MODAL_WATCHLISTS = "watchlists";

export type ManagerIntent =
  /** "Manage watchlists…", a deep link: the list shown, focus on it. */
  | { readonly kind: "open"; readonly listId?: string | undefined }
  /** "+", "Create watchlist": a new list, named in place. */
  | { readonly kind: "create" }
  /** The tab menu's Rename, Duplicate and Delete…, the empty list's "Import a list", the add popover's "Paste several…". */
  | {
      readonly kind: "rename" | "duplicate" | "delete" | "import" | "paste";
      readonly listId: string;
    };

/** SCR-101's deep link on one list: R-111 with the modal open (the empty list's "Import a list" points here). */
export const managerHref = (listId: string): string =>
  `/watchlist/${encodeURIComponent(listId)}?${MODAL_PARAM}=${MODAL_WATCHLISTS}`;
