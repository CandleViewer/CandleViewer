/**
 * Node and pane ids come from an injected minter, so the package needs no `crypto` global and
 * tests are deterministic. The app keeps one minter per dock, so ids never repeat in a session.
 */
export type IdMinter = () => string;

/** `prefix1`, `prefix2`, ...: unique for the minter's lifetime. */
export function counterMinter(prefix = "n"): IdMinter {
  let next = 0;
  return () => {
    next += 1;
    return `${prefix}${next}`;
  };
}
