// E14-X03 (#549) test-plan scratch: a drawing label through a raw-HTML sink. Never merged.
export function ScratchHtmlLabel({ label }: { label: string }) {
  return <span dangerouslySetInnerHTML={{ __html: label }} />;
}
