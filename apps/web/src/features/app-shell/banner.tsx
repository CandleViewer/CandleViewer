import type { JSX } from "react";
import { DegradedBanner } from "../system-states/DegradedBanner";
import { VersionBannerSlot } from "../system-states/VersionBanner";
import { ConnectionRegionSlot } from "./ConnectionRegionSlot";

/**
 * The SCR-152 / SCR-153 / SCR-157 banner slot's content (E17-D02 §4.1, §6, §8; E10-D03 §2.1): the
 * CMP-077 connection region (0 px while live), CMP-092's degraded rows below it, then the
 * update-available band (nothing while the builds match).
 */
export function ShellBanner(): JSX.Element {
  return (
    <>
      <ConnectionRegionSlot />
      <DegradedBanner />
      <VersionBannerSlot />
    </>
  );
}
