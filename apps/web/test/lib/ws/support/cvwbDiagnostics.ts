// What `validateCvwb` may say when it refuses a binary body (#415 E17-X02, #4112): the decoders' own
// diagnostics (packages/protocol/src/runtime/index.ts), which are fixed words and header integers,
// never payload bytes, and the codec's fallback for an untyped throw. The fuzz property
// (codec.fuzz.test.ts) refuses any other message; codec.diagnostics.test.ts checks this list
// against every diagnostic the decoders throw, so a new one fails a PR rather than the nightly.
const INT = String.raw`\d+`; // a header integer
const FITS = String.raw`count=${INT} x ${INT} bytes exceeds the ${INT} bytes left in the buffer`;

export const DIAGNOSTICS = [
  String.raw`binary frame too short for the ${INT}-byte common header \(got ${INT} bytes\)`,
  String.raw`bad magic 0x[0-9a-f]+, expected 0x[0-9a-f]+ \("CVWB"\)`,
  String.raw`unknown body_kind ${INT}`,
  String.raw`unsupported \(body_kind=${INT}, format_version=${INT}\); expected format_version ${INT}`,
  String.raw`(?:book levels|trades|footprint groups|footprint group ${INT}|heatmap rows): ${FITS}`,
  String.raw`(?:book|trade|bar) record ${INT} runs past the buffer \(record_count=${INT}\)`,
  String.raw`footprint group ${INT} prefix runs past the buffer \(record_count=${INT}\)`,
  String.raw`footprint cell ${INT} in group ${INT} runs past the buffer \(cell_count=${INT}\)`,
  String.raw`heatmap row ${INT} runs past the buffer \(row_count=${INT}\)`,
  String.raw`heatmap column record_count=${INT}, expected 1`,
  String.raw`invalid (?:book|trade) side byte ${INT} at record ${INT}`,
  String.raw`book snapshot missing its ${INT}-byte xu/xseq trailer`,
  String.raw`bars body is ${INT} bytes, expected ${INT} for record_count=${INT}`,
  "heatmap column body shorter than its fixed prefix",
  "binary body is undecodable",
];

export const DIAGNOSTIC = new RegExp(`^(?:${DIAGNOSTICS.join("|")})$`);
