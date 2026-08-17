import {
  isElementSelfHidden,
  shouldSkipContentSubtree,
} from "./domVisibility";

const ownUiRoots = new WeakSet<Node>();
const TEXT_SEPARATOR_TAGS = new Set([
  "ADDRESS",
  "ARTICLE",
  "ASIDE",
  "BLOCKQUOTE",
  "BR",
  "DD",
  "DIV",
  "DL",
  "DT",
  "FIGCAPTION",
  "FIGURE",
  "FOOTER",
  "H1",
  "H2",
  "H3",
  "H4",
  "H5",
  "H6",
  "HEADER",
  "HR",
  "LI",
  "MAIN",
  "OL",
  "P",
  "PRE",
  "SECTION",
  "TABLE",
  "TBODY",
  "TD",
  "TFOOT",
  "TH",
  "THEAD",
  "TR",
  "UL",
]);

/**
 * Registers a root that was actually created by the extension.
 *
 * DOM selectors are deliberately not used as a trust boundary: a page can
 * create elements with the same ids or classes as the extension UI.
 */
export function registerOwnUiRoot<T extends Element>(root: T): T {
  ownUiRoots.add(root);
  return root;
}

export function isInsideOwnUi(node: Node | null): boolean {
  let current = node;

  while (current) {
    if (ownUiRoots.has(current)) return true;
    current = current.parentNode;
  }

  return false;
}

interface TextNodeOptions {
  visibleOnly?: boolean;
  ignoreRootVisibility?: boolean;
}

function textNodesExcludingOwnUi(
  root: Node,
  options: TextNodeOptions = {},
): Node[] {
  if (isInsideOwnUi(root)) return [];

  const textNodes: Node[] = [];
  const stack = [root];

  while (stack.length > 0) {
    const node = stack.pop()!;
    if (node !== root && ownUiRoots.has(node)) continue;

    if (node.nodeType === 1) {
      const element = node as Element;
      if (shouldSkipContentSubtree(element)) continue;
      if (
        options.visibleOnly &&
        !(options.ignoreRootVisibility && node === root) &&
        isElementSelfHidden(element)
      ) {
        continue;
      }
    }

    if (node.nodeType === 3 || node.nodeType === 4) {
      textNodes.push(node);
      continue;
    }

    const children = Array.from(node.childNodes);
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push(children[index]);
    }
  }

  return textNodes;
}

/** Returns page text excluding extension UI and non-content/editor subtrees. */
export function getTextContentExcludingOwnUi(root: Node): string {
  return textNodesExcludingOwnUi(root)
    .map((node) => node.nodeValue ?? "")
    .join("");
}

/**
 * Approximates rendered text without forcing layout. Hidden and editable
 * subtrees are omitted so collapsed messages and compose windows do not leak
 * into an analysis payload.
 */
export function getVisibleTextContentExcludingOwnUi(
  root: Node,
  options: { ignoreRootVisibility?: boolean } = {},
): string {
  if (isInsideOwnUi(root)) return "";

  const parts: string[] = [];
  const append = (node: Node): void => {
    if (node !== root && ownUiRoots.has(node)) return;

    if (node.nodeType === 3 || node.nodeType === 4) {
      parts.push(node.nodeValue ?? "");
      return;
    }

    if (node.nodeType === 1) {
      const element = node as Element;
      if (shouldSkipContentSubtree(element)) return;
      if (
        !(options.ignoreRootVisibility && node === root) &&
        isElementSelfHidden(element)
      ) {
        return;
      }

      const separates =
        node !== root &&
        TEXT_SEPARATOR_TAGS.has((element.tagName ?? "").toUpperCase());
      if (separates) parts.push("\n");
      if ((element.tagName ?? "").toUpperCase() === "BR") return;

      for (const child of Array.from(node.childNodes)) append(child);
      if (separates) parts.push("\n");
      return;
    }

    for (const child of Array.from(node.childNodes)) append(child);
  };

  append(root);
  return parts
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

/** Rebuilds selected text while omitting any registered UI subtree. */
export function getRangeTextExcludingOwnUi(root: Node, range: Range): string {
  const parts: string[] = [];

  for (const node of textNodesExcludingOwnUi(root)) {
    try {
      if (!range.intersectsNode(node)) continue;
    } catch {
      continue;
    }

    const value = node.nodeValue ?? "";
    const start = node === range.startContainer ? range.startOffset : 0;
    const end = node === range.endContainer ? range.endOffset : value.length;
    parts.push(value.slice(start, end));
  }

  return parts.join("");
}
