// E29-S01 (#911) the Positions REST stubs: they live in `@candleviewer/fixtures/e2e` beside the session
// stubs (E10-Q02) so the Electron smoke uses them too; this path is the web specs' support entry.
export {
  goldenPositions,
  POSITIONS_FIXTURE,
  stubPositions,
  type PositionsSession,
  type PositionsStubs,
} from "@candleviewer/fixtures/e2e";
