import { describe, expect, test } from "vitest";
import {
  getRangeTextExcludingOwnUi,
  getTextContentExcludingOwnUi,
  isInsideOwnUi,
  registerOwnUiRoot,
} from "./ownUi";

type FakeNode = {
  childNodes: FakeNode[];
  id?: string;
  nodeType: number;
  nodeValue: string | null;
  parentNode: FakeNode | null;
};

function element(children: FakeNode[] = [], id?: string): FakeNode {
  const node: FakeNode = {
    childNodes: children,
    id,
    nodeType: 1,
    nodeValue: null,
    parentNode: null,
  };

  for (const child of children) child.parentNode = node;
  return node;
}

function text(value: string): FakeNode {
  return {
    childNodes: [],
    nodeType: 3,
    nodeValue: value,
    parentNode: null,
  };
}

function asNode(node: FakeNode): Node {
  return node as unknown as Node;
}

function asElement(node: FakeNode): Element {
  return node as unknown as Element;
}

describe("own UI boundary", () => {
  test("recognizes a registered root and all of its descendants", () => {
    const child = element([text("button")]);
    const root = element([child]);
    registerOwnUiRoot(asElement(root));

    expect(isInsideOwnUi(asNode(root))).toBe(true);
    expect(isInsideOwnUi(asNode(child))).toBe(true);
    expect(isInsideOwnUi(asNode(child.childNodes[0]))).toBe(true);
  });

  test("does not trust a page element just because it has an extension id", () => {
    const lookalike = element([text("page content")], "pg-panel");

    expect(isInsideOwnUi(asNode(lookalike))).toBe(false);
    expect(isInsideOwnUi(asNode(lookalike.childNodes[0]))).toBe(false);
  });

  test("excludes registered UI subtrees from collected text", () => {
    const ownText = text("guardian controls");
    const ownRoot = element([ownText]);
    const page = element([text("before "), ownRoot, text("after")]);
    registerOwnUiRoot(asElement(ownRoot));

    expect(getTextContentExcludingOwnUi(asNode(page))).toBe("before after");
    expect(getTextContentExcludingOwnUi(asNode(ownRoot))).toBe("");
  });

  test("excludes registered UI text from a range", () => {
    const before = text("before ");
    const ownRoot = element([text("panel text")]);
    const after = text("after");
    const page = element([before, ownRoot, after]);
    registerOwnUiRoot(asElement(ownRoot));

    const range = {
      endContainer: after,
      endOffset: after.nodeValue!.length,
      intersectsNode: () => true,
      startContainer: before,
      startOffset: 0,
    } as unknown as Range;

    expect(getRangeTextExcludingOwnUi(asNode(page), range)).toBe(
      "before after",
    );
  });
});
