export declare const SOURCE_DIR: string;
export declare const OUTPUT_DIR: string;
export declare const ORIGINS: readonly string[];

/** A source the generator refuses; the message starts with the file. */
export declare class IconSourceError extends Error {}

/** A geometry element of a source: its tag, then its `[attribute, value]` pairs in order. */
export type IconGeometry = readonly [
  tag: string,
  attributes: readonly (readonly [string, string])[],
];

export interface ParsedIconSource {
  /** The Lucide glyph the root's `class` names, or `null` for a custom glyph. */
  readonly glyph: string | null;
  readonly children: readonly IconGeometry[];
}

export interface IconSourceFile {
  readonly name: string;
  readonly origin: string;
  /** Its path in the package: `src/icons/source/<origin>/<name>.svg`. */
  readonly file: string;
}

export declare function parseIconSource(text: string, file: string): ParsedIconSource;
export declare function componentName(name: string): string;
export declare function iconSources(root?: string): IconSourceFile[];
export declare function renderIconModules(root?: string): Map<string, string>;
/** The command line on the package at `root` (default packages/ui): its exit code. */
export declare function run(args: readonly string[], root?: string): number;
