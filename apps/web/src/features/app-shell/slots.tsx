/**
 * Shell slots (E10-S01 S1, #304). The contract for content that later slices put into the shell
 * chrome without editing it:
 *
 * - `ShellBannerSlot`: one full-width row between the top bar and the canvas (D03 §2, 0 px when
 *   empty). It has no landmark of its own; a banner brings its own role (`status` / `alert`).
 * - `ShellConnectionSlot`: inside the header (`banner`) landmark. S3 fills it with the CMP-076 chip
 *   and the shell's live-region pair (`ConnectionStatusSlot`).
 * - `ShellCanvasOverlaySlot`: a positioned sibling of the route outlet inside `main`, covering the
 *   visible canvas; #306 slice 4b fills it with the CMP-077 region (`ConnectionRegionSlot`). It never wraps or re-renders the outlet. Its layer ignores the pointer, so
 *   overlay content that takes input sets `pointer-events: auto` itself.
 *
 * Each slot renders nothing until a later slice (#306 slices 3 and 4b) fills it by editing only
 * this file. A slot reads its own state; it takes no props from the layout, so filling one never
 * re-renders the outlet.
 */
import type { JSX } from "react";
import { ConnectionRegionSlot } from "./ConnectionRegionSlot";
import { ConnectionStatusSlot } from "./ConnectionStatusSlot";
import { DegradedBanner } from "../system-states/DegradedBanner";

/** A shell slot: a prop-less component that renders its content or nothing. */
export type ShellSlot = () => JSX.Element | null;

export const ShellBannerSlot: ShellSlot = DegradedBanner;

export const ShellConnectionSlot: ShellSlot = ConnectionStatusSlot;

/** #306 slice 4b: the CMP-077 connection region (SCR-152), empty while live. */
export const ShellCanvasOverlaySlot: ShellSlot = ConnectionRegionSlot;
