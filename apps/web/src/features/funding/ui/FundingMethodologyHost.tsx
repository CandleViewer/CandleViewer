// E24-S04 (#779): binds every CMP-227 badge in the funding surfaces to CMP-069. SCR-058 has no funding section
// and `DetectorId` is the one union (NG-1, DV-5), so `Enter` on the chip opens CMP-069 with D02's F10 sentence;
// `Esc` returns focus to the chip that opened it (15 CMP-069 A11y).
import { useCallback, useRef, useState, type JSX, type ReactNode } from "react";
import { EstimatedMethodologyProvider, InfoPanel, type DetectorId } from "@candleviewer/ui";
import * as copy from "./copy";

export function FundingMethodologyHost({
  children,
}: {
  readonly children: ReactNode;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  // the badge passes itself: `document.activeElement` is `body` after a mouse click in Safari and Firefox/macOS
  const openMethodology = useCallback((_detector: DetectorId, badge: HTMLElement): void => {
    opener.current = badge;
    setOpen(true);
  }, []);
  return (
    <EstimatedMethodologyProvider openMethodology={openMethodology}>
      {children}
      <InfoPanel
        title={copy.PANE_LABEL}
        relatedDetector="funding"
        content={<p>{copy.PREDICTED_PROVENANCE}</p>}
        open={open}
        onOpenChange={setOpen}
        trigger={() => null}
        fallbackFocusRef={opener}
      />
    </EstimatedMethodologyProvider>
  );
}
