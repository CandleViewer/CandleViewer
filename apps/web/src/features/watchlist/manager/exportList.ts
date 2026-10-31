/**
 * SCR-101's "Export Majors" (E08-D07 §4.4): the list as shown, saved as `Majors.txt` through a transient link (a
 * plain-text download, never a navigation, nothing uploaded), with `watchlist.exported` (`14` SCR-101).
 */
import { reportWatchlist } from "../analytics";
import { exportFile } from "./symbolText";

export function exportList(
  list: { readonly id: string; readonly name: string; readonly symbols: readonly string[] },
  at: Date,
): void {
  const { fileName, text } = exportFile(list.name, list.symbols, at);
  if (typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
  reportWatchlist({ name: "watchlist.exported", watchlist_id: list.id });
}
