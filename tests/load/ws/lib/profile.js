/* The profile table, resolved: shared by ws_load.js and the Node checks (pure, no k6 imports).
 * tests/load/ws/profiles.json is the one source; bench/ws/profiles.py reads the same file and
 * resolves it the same way (a test pins that the two agree). */

/** A profile with its `base` and the table's `defaults` applied; the profile wins. */
export function resolve(table, name) {
  const raw = table.profiles[name];
  if (raw === undefined) throw new Error(`unknown profile ${name}`);
  const { base, ...own } = raw;
  return { ...(base === undefined ? table.defaults : resolve(table, base)), ...own };
}

/** One connection's subscriptions: the workspace's families (those the profile names) on each of its
 * symbols, but `bars` on the first `bars_symbols` and `footprint` on the first `footprint_symbols`
 * only: both lease a bar series, and the gateway admits 8 distinct series per user (23 6.1). */
export function topicsFor(table, prof) {
  const cap = { bars: prof.bars_symbols, footprint: prof.footprint_symbols };
  const out = [];
  table.symbols.slice(0, prof.symbols).forEach((symbol, i) => {
    for (const fam of table.workspaces[prof.workspace]) {
      const limit = cap[fam] === undefined ? prof.symbols : cap[fam];
      if (prof.families.includes(fam) && i < limit) {
        const t = table.topics[fam];
        out.push({ fam, ch: t.ch.replace("{s}", symbol), opts: t.opts, symbol });
      }
    }
  });
  return out;
}

const WS_PATH = /^(\/[A-Za-z0-9_~-][A-Za-z0-9._~-]*)*\/ws$/;

/** The fixture's WebSocket URL: loopback only, at `/ws` or a prefix and `/ws` (`/api/v1/ws`, 23 2.1).
 * bench/ws/profiles.py `ws_path` accepts the same paths (a test pins that the two agree). */
export function wsUrl(port, path) {
  if (!WS_PATH.test(path)) throw new Error(`ws path ${path}: expected /ws or a prefix and /ws`);
  return `ws://127.0.0.1:${port}${path}`;
}
