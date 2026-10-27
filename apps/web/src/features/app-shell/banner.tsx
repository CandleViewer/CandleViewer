import type { JSX } from "react";
import { DegradedBanner } from "../system-states/DegradedBanner";
import { ConnectionRegionSlot } from "./ConnectionRegionSlot";

/**
 * The SCR-152 / SCR-153 banner slot's content (E17-D02 §4.1, §6, §8): the CMP-077 connection
 * region (0 px while live), then CMP-092's degraded rows below it.
 */
export function ShellBanner(): JSX.Element {
  return (
    <>
      <ConnectionRegionSlot />
      <DegradedBanner />
    </>
  );
}
