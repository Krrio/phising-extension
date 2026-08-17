import { afterEach, describe, expect, test, vi } from "vitest";
import { getVisibleTextContentExcludingOwnUi } from "./ownUi";

type FakeNode = {
  childNodes: FakeNode[];
  getAttribute?: (name: string) => string | null;
  hasAttribute?: (name: string) => boolean;
  nodeType: number;
  nodeValue: string | null;
  ownerDocument?: { defaultView?: undefined };
  parentNode: FakeNode | null;
  style?: Record<string, string>;
  tagName?: string;
};

function text(value: string): FakeNode {
  return {
    childNodes: [],
    nodeType: 3,
    nodeValue: value,
    parentNode: null,
  };
}

function element(
  children: FakeNode[],
  attributes: Record<string, string> = {},
  style: Record<string, string> = {},
): FakeNode {
  const node: FakeNode = {
    childNodes: children,
    getAttribute: (name) => attributes[name] ?? null,
    hasAttribute: (name) =>
      Object.prototype.hasOwnProperty.call(attributes, name),
    nodeType: 1,
    nodeValue: null,
    ownerDocument: {},
    parentNode: null,
    style,
    tagName: "DIV",
  };

  for (const child of children) child.parentNode = node;
  return node;
}

function asNode(node: FakeNode): Node {
  return node as unknown as Node;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("visible content extraction", () => {
  test("keeps inline text stable when a phrase is wrapped in a mark", () => {
    vi.stubGlobal("getComputedStyle", () => ({
      contentVisibility: "visible",
      display: "inline",
      opacity: "1",
      visibility: "visible",
    }));

    const unsplit = element([text("urgent action!")]);
    const wrapped = element([
      text("urgent "),
      { ...element([text("action")]), tagName: "MARK" },
      text("!"),
    ]);

    expect(getVisibleTextContentExcludingOwnUi(asNode(wrapped))).toBe(
      getVisibleTextContentExcludingOwnUi(asNode(unsplit)),
    );
  });

  test("keeps a separator between block elements", () => {
    vi.stubGlobal("getComputedStyle", () => ({
      contentVisibility: "visible",
      display: "block",
      opacity: "1",
      visibility: "visible",
    }));

    const root = element([
      element([text("first")]),
      element([text("second")]),
    ]);

    expect(getVisibleTextContentExcludingOwnUi(asNode(root))).toBe(
      "first second",
    );
  });

  test("omits aria-hidden, CSS-hidden and editable subtrees", () => {
    vi.stubGlobal("getComputedStyle", (target: FakeNode) => ({
      contentVisibility: target.style?.contentVisibility ?? "visible",
      display: target.style?.display ?? "block",
      opacity: target.style?.opacity ?? "1",
      visibility: target.style?.visibility ?? "visible",
    }));

    const root = element([
      text("visible"),
      element([text("collapsed")], { "aria-hidden": "true" }),
      element([text("css hidden")], {}, { display: "none" }),
      element([text("draft")], { contenteditable: "true" }),
      element([text("end")]),
    ]);

    expect(getVisibleTextContentExcludingOwnUi(asNode(root))).toBe(
      "visible end",
    );
  });

  test("can read a root hidden by Guardian while retaining hidden descendants", () => {
    vi.stubGlobal("getComputedStyle", (target: FakeNode) => ({
      contentVisibility: "visible",
      display: target.style?.display ?? "block",
      opacity: "1",
      visibility: "visible",
    }));

    const root = element(
      [text("message"), element([text("old quote")], { hidden: "" })],
      {},
      { display: "none" },
    );

    expect(getVisibleTextContentExcludingOwnUi(asNode(root))).toBe("");
    expect(
      getVisibleTextContentExcludingOwnUi(asNode(root), {
        ignoreRootVisibility: true,
      }),
    ).toBe("message");
  });
});
