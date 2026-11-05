// Test helper: a small CSS cascade over a stylesheet's top-level rules (specificity, then source order).
/** The top-level rules of a stylesheet (an at-rule's block is skipped whole): each selector and its body. */
export function topLevelRules(sheet: string): { readonly selector: string; readonly body: string }[] {
  const text = sheet.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules: { selector: string; body: string }[] = [];
  let depth = 0;
  let start = 0;
  let head = "";
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === "{") {
      if (depth === 0) {
        head = text.slice(start, i).trim();
        start = i + 1;
      }
      depth += 1;
    } else if (text[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        if (!head.startsWith("@")) {
          for (const selector of head.split(/,(?![^(]*\))/))
            rules.push({ selector: selector.trim(), body: text.slice(start, i) });
        }
        start = i + 1;
      }
    }
  }
  return rules;
}

/** CSS specificity (ids, classes / attributes / pseudo-classes, types) of one selector: enough for these sheets. */
export function specificity(selector: string): [number, number, number] {
  let rest = selector.replace(/::[\w-]+/g, "").replace(/:where\((?:[^()]|\([^()]*\))*\)/g, "");
  const total: [number, number, number] = [0, 0, 0];
  rest = rest.replace(/:(?:is|not|has)\(((?:[^()]|\([^()]*\))*)\)/g, (_, args: string) => {
    const best = args
      .split(/,(?![^(]*\))/)
      .map((arg) => specificity(arg.trim()))
      .sort((a, b) => b[0] - a[0] || b[1] - a[1] || b[2] - a[2])[0] ?? [0, 0, 0];
    total[0] += best[0];
    total[1] += best[1];
    total[2] += best[2];
    return " ";
  });
  total[0] += (rest.match(/#[\w-]+/g) ?? []).length;
  total[1] += (rest.match(/\.[\w-]+|\[[^\]]*\]|:[\w-]+(?:\([^)]*\))?/g) ?? []).length;
  total[2] += rest
    .replace(/\[[^\]]*\]|[.#:][\w-]+(?:\([^)]*\))?/g, " ")
    .split(/[\s>+~]+/)
    .filter((part) => /^[a-z][\w-]*$/i.test(part)).length;
  return total;
}

/** The `property` the cascade gives `element` from `sheet`'s top-level rules: highest specificity, then the last. */
export function cascadedProperty(
  sheet: string,
  element: Element,
  property: string,
): string | undefined {
  let winner: { readonly spec: [number, number, number]; readonly value: string } | undefined;
  for (const { selector, body } of topLevelRules(sheet)) {
    const value = new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*([^;]+)`).exec(body)?.[1]?.trim();
    if (value === undefined || selector.includes("::")) continue;
    let matches = false;
    try {
      matches = element.matches(selector);
    } catch {
      matches = false;
    }
    if (!matches) continue;
    const spec = specificity(selector);
    const [a, b, c] = winner?.spec ?? [-1, -1, -1];
    if (spec[0] > a || (spec[0] === a && (spec[1] > b || (spec[1] === b && spec[2] >= c))))
      winner = { spec, value };
  }
  return winner?.value;
}

export const cascadedColor = (sheet: string, element: Element): string | undefined =>
  cascadedProperty(sheet, element, "color");

