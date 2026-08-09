const ownUiRoots = new WeakSet<Node>();

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

function textNodesExcludingOwnUi(root: Node): Node[] {
  if (isInsideOwnUi(root)) return [];

  const textNodes: Node[] = [];
  const stack = [root];

  while (stack.length > 0) {
    const node = stack.pop()!;
    if (node !== root && ownUiRoots.has(node)) continue;

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

/** Returns the same text as textContent, excluding registered UI subtrees. */
export function getTextContentExcludingOwnUi(root: Node): string {
  return textNodesExcludingOwnUi(root)
    .map((node) => node.nodeValue ?? "")
    .join("");
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
