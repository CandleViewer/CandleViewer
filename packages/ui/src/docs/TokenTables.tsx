import type { JSX } from "react";

export interface TokenRow {
  /**
   * The token's path in `build/ts/tokens.ts`, e.g. `color.buy.default`; a typography token has one
   * row per field, e.g. `type.ui.label.fontSize`.
   */
  readonly path: string;
  /** The custom property each theme bundle defines for it, e.g. `--color-buy-default`. */
  readonly property: string;
  readonly value: string;
}

const isGroup = (node: unknown): node is object =>
  typeof node === "object" && node !== null && !Array.isArray(node);
/** The fields of a typography value. */
const TYPOGRAPHY = ["fontFamily", "fontSize", "fontWeight", "letterSpacing", "lineHeight"];
/** The fields of the DTCG composite types (shadow, typography, border, transition, stroke style). */
const COMPOSITES = [
  ["color", "offsetX", "offsetY", "blur", "spread", "inset"],
  TYPOGRAPHY,
  ["color", "width", "style"],
  ["duration", "delay", "timingFunction"],
  ["dashArray", "lineCap"],
];
/** An object of one composite type's fields is a single token's value, not a group of tokens. */
const isComposite = (node: object): boolean =>
  COMPOSITES.some((fields) => Object.keys(node).every((key) => fields.includes(key)));
const isTypography = (node: object): boolean =>
  Object.keys(node).length > 0 && Object.keys(node).every((key) => TYPOGRAPHY.includes(key));
/** A field as the suffix of its custom property: `fontSize` is `font-size`. */
const cssSuffix = (field: string): string =>
  field.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
const HEX = /^#[0-9a-f]{6}([0-9a-f]{2})?$/i;

/** Every token of the generated tree, in its order, with its custom property. */
export function tokenRows(tree: object, path: readonly string[] = []): TokenRow[] {
  return Object.entries(tree).flatMap(([key, value]: [string, unknown]) => {
    const at = [...path, key];
    if (isGroup(value) && isTypography(value)) {
      // The theme bundles write a typography token as one custom property per field, not one value.
      return Object.entries(value).map(([field, part]: [string, unknown]) => ({
        path: [...at, field].join("."),
        property: `--${at.join("-")}-${cssSuffix(field)}`,
        value: typeof part === "string" ? part : JSON.stringify(part),
      }));
    }
    if (isGroup(value) && !isComposite(value)) return tokenRows(value, at);
    const shown = typeof value === "string" ? value : JSON.stringify(value);
    return [{ path: at.join("."), property: `--${at.join("-")}`, value: shown }];
  });
}

/**
 * The Foundations token tables: one per top-level group of the generated `tokens` object. Values are
 * the dark set that `build/ts/tokens.ts` carries; a colour's swatch paints its custom property.
 */
export function TokenTables({ tokens }: { readonly tokens: object }): JSX.Element {
  return (
    <>
      {Object.entries(tokens).map(([group, tree]: [string, unknown]) => (
        <table key={group}>
          <caption>{group}</caption>
          <thead>
            <tr>
              <th scope="col">Token</th>
              <th scope="col">Custom property</th>
              <th scope="col">Value</th>
            </tr>
          </thead>
          <tbody>
            {tokenRows({ [group]: tree }).map(({ path, property, value }) => (
              <tr key={path}>
                <th scope="row">{path}</th>
                <td>
                  <code>{property}</code>
                </td>
                <td>
                  {HEX.test(value) ? (
                    <span
                      aria-hidden="true"
                      style={{
                        display: "inline-block",
                        inlineSize: "1em",
                        blockSize: "1em",
                        marginInlineEnd: "0.5em",
                        backgroundColor: `var(${property}, ${value})`,
                        border: "thin solid currentColor",
                      }}
                    />
                  ) : null}
                  <code>{value}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </>
  );
}
