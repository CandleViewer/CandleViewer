/**
 * Where the overview links (E42-S01): manifest routes only. The strip's items and the tiles'
 * headings take their paths from the app's route table, never from a string the server sent, so a
 * read can change what a link says, never where it goes. E42-D01's tile → screen map (§6 Anatomy).
 */
import { ROUTE_MANIFEST } from "../../../routes/manifest";

const PATHS: ReadonlyMap<string, string> = new Map(ROUTE_MANIFEST.map((e) => [e.id, e.path]));

/** The routes the overview links to, by what they are. */
export const ADMIN_LINKS = {
  risk: "R-150", // SCR-071, the Trading safety tile's first screen
  users: "R-301", // SCR-121; E42-S02 builds its capacity line and the Record tier dialog there
  accounts: "R-310", // SCR-125
  profiles: "R-330", // SCR-130
  recorder: "R-340", // SCR-140
  health: "R-350", // SCR-143
  flags: "R-351", // SCR-145
  security: "R-354", // SCR-137
  maintenance: "R-356", // SCR-148
  audit: "R-360", // SCR-135; SCR-136's per-entry link is E42-S04's
} as const;

export type AdminLink = keyof typeof ADMIN_LINKS;

/** The manifest path of `link`, or `undefined` if the table has none (then nothing links). */
export function routePath(link: AdminLink): string | undefined {
  return PATHS.get(ADMIN_LINKS[link]);
}
