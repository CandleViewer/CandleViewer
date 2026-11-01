/**
 * CMP-197's placement, pure (E11-S07, BQ-18; E11-D02 §7.3 rules 1-3 and 5, D10). All numbers are CSS
 * px in the plot's own space. The last-price band shift (rule 4) waits for the last-price y (a G-row).
 */

/** E11-D02 D10: 16 px right of and below the anchor (the ticket's 12 px is a C-row). */
export const TOOLTIP_OFFSET_PX = 16;
/** The edge clearance for the flip and the dock. */
export const TOOLTIP_EDGE_PX = 8;
/** A pane shorter than the box plus this docks the box to its top-right corner. */
export const TOOLTIP_DOCK_SLACK_PX = 32;

export interface Size {
  readonly width: number;
  readonly height: number;
}
export interface Point {
  readonly x: number;
  readonly y: number;
}
export interface TooltipPlacement extends Point {
  readonly docked: boolean;
  readonly flippedX: boolean;
  readonly flippedY: boolean;
}

const clamp = (v: number, lo: number, hi: number): number => Math.max(lo, Math.min(v, hi));

export function placeTooltip(anchor: Point, box: Size, plot: Size): TooltipPlacement {
  if (plot.height < box.height + TOOLTIP_DOCK_SLACK_PX) {
    return {
      x: Math.max(0, plot.width - box.width - TOOLTIP_EDGE_PX),
      y: Math.min(TOOLTIP_EDGE_PX, Math.max(0, plot.height - box.height)),
      docked: true,
      flippedX: false,
      flippedY: false,
    };
  }
  const flippedX = anchor.x + TOOLTIP_OFFSET_PX + box.width > plot.width - TOOLTIP_EDGE_PX;
  const flippedY = anchor.y + TOOLTIP_OFFSET_PX + box.height > plot.height - TOOLTIP_EDGE_PX;
  const x = flippedX ? anchor.x - TOOLTIP_OFFSET_PX - box.width : anchor.x + TOOLTIP_OFFSET_PX;
  const y = flippedY ? anchor.y - TOOLTIP_OFFSET_PX - box.height : anchor.y + TOOLTIP_OFFSET_PX;
  return {
    x: clamp(x, 0, Math.max(0, plot.width - box.width)),
    y: clamp(y, 0, Math.max(0, plot.height - box.height)),
    docked: false,
    flippedX,
    flippedY,
  };
}
