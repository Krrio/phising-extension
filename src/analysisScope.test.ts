import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import {
  collectAnalysisScopes,
  findAnalysisRoot,
  resolveAnalysisScope,
} from "./analysisScope";

type Attributes = Record<string, string>;

class FakeElement {
  readonly children: FakeElement[] = [];
  readonly nodeType = 1;
  readonly style: Record<string, string> = {};
  parentElement: FakeElement | null = null;
  private ownText: string;
  private readonly attributes = new Map<string, string>();

  constructor(
    readonly tagName: string,
    attributes: Attributes = {},
    text = "",
  ) {
    this.ownText = text;
    for (const [name, value] of Object.entries(attributes)) {
      if (name === "style") {
        for (const declaration of value.split(";")) {
          const [property, propertyValue] = declaration.split(":");
          if (property?.trim() && propertyValue?.trim()) {
            this.style[property.trim()] = propertyValue.trim();
          }
        }
      } else {
        this.attributes.set(name, value);
      }
    }
  }

  get parentNode(): FakeElement | null {
    return this.parentElement;
  }

  get textContent(): string {
    return this.ownText + this.children.map((child) => child.textContent).join("");
  }

  set textContent(value: string) {
    this.ownText = value;
  }

  get hidden(): boolean {
    return this.hasAttribute("hidden");
  }

  get isConnected(): boolean {
    let current: FakeElement | null = this;
    while (current?.parentElement) current = current.parentElement;
    return current === testBody;
  }

  append(...children: FakeElement[]): this {
    for (const child of children) {
      child.parentElement = this;
      this.children.push(child);
    }
    return this;
  }

  contains(other: FakeElement): boolean {
    let current: FakeElement | null = other;
    while (current) {
      if (current === this) return true;
      current = current.parentElement;
    }
    return false;
  }

  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }

  getAttributeNames(): string[] {
    return Array.from(this.attributes.keys());
  }

  hasAttribute(name: string): boolean {
    return this.attributes.has(name);
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  matches(selectorList: string): boolean {
    return splitSelectorList(selectorList).some((selector) =>
      this.matchesSimpleSelector(selector),
    );
  }

  closest<T extends Element = Element>(selector: string): T | null {
    let current: FakeElement | null = this;
    while (current) {
      if (current.matches(selector)) return current as unknown as T;
      current = current.parentElement;
    }
    return null;
  }

  querySelector<T extends Element = Element>(selector: string): T | null {
    return this.querySelectorAll<T>(selector)[0] ?? null;
  }

  querySelectorAll<T extends Element = Element>(selector: string): T[] {
    const matches: T[] = [];
    const visit = (element: FakeElement) => {
      for (const child of element.children) {
        if (child.matches(selector)) matches.push(child as unknown as T);
        visit(child);
      }
    };
    visit(this);
    return matches;
  }

  getClientRects(): Array<Record<string, never>> {
    return isRendered(this) ? [{}] : [];
  }

  private matchesSimpleSelector(selector: string): boolean {
    const normalized = selector.trim();
    if (!normalized) return false;

    const isMatch = normalized.match(/^:is\((.*)\)$/);
    if (isMatch) return this.matches(isMatch[1]);

    if (normalized.startsWith(".")) {
      return (this.getAttribute("class") ?? "")
        .split(/\s+/)
        .includes(normalized.slice(1));
    }

    const attributeMatch = normalized.match(
      /^([a-z][\w-]*)?\[([^\]=\s]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\]]+)))?\]$/i,
    );
    if (attributeMatch) {
      const [, tagName, attributeName, doubleQuoted, singleQuoted, bare] =
        attributeMatch;
      if (tagName && this.tagName.toLowerCase() !== tagName.toLowerCase()) {
        return false;
      }
      if (!this.hasAttribute(attributeName)) return false;

      const expected = doubleQuoted ?? singleQuoted ?? bare?.trim();
      return expected === undefined || this.getAttribute(attributeName) === expected;
    }

    return this.tagName.toLowerCase() === normalized.toLowerCase();
  }
}

function splitSelectorList(selectorList: string): string[] {
  const selectors: string[] = [];
  let nesting = 0;
  let start = 0;

  for (let index = 0; index < selectorList.length; index += 1) {
    const character = selectorList[index];
    if (character === "(") nesting += 1;
    if (character === ")") nesting -= 1;
    if (character === "," && nesting === 0) {
      selectors.push(selectorList.slice(start, index).trim());
      start = index + 1;
    }
  }

  selectors.push(selectorList.slice(start).trim());
  return selectors;
}

function isRendered(element: FakeElement): boolean {
  let current: FakeElement | null = element;
  while (current) {
    if (current.hidden || current.getAttribute("aria-hidden") === "true") {
      return false;
    }
    if (
      current.style.display === "none" ||
      current.style.visibility === "hidden" ||
      current.style.visibility === "collapse"
    ) {
      return false;
    }
    current = current.parentElement;
  }
  return true;
}

function element(
  tagName = "div",
  attributes: Attributes = {},
  text = "",
): FakeElement {
  return new FakeElement(tagName, attributes, text);
}

function asElement(value: FakeElement): Element {
  return value as unknown as Element;
}

let testBody: FakeElement;

beforeEach(() => {
  testBody = element("body");
  vi.stubGlobal("Element", FakeElement);
  vi.stubGlobal("HTMLElement", FakeElement);
  vi.stubGlobal("document", { body: testBody });
  vi.stubGlobal("getComputedStyle", (target: FakeElement) => ({
    display: target.style.display ?? "block",
    visibility: target.style.visibility ?? "visible",
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("findAnalysisRoot", () => {
  test.each([
    ["data-message-id", "#msg-f:123"],
    ["data-legacy-message-id", "18f0123456789abc"],
  ])("uses Gmail's semantic %s boundary", (attribute, value) => {
    const message = element("div", { [attribute]: value });
    const nestedListItem = element("div", { role: "listitem" });
    const gmailBody = element("div", { class: "a3s ii gt" });
    const selectedText = element("span", {}, "Pilnie potwierdź swoje konto.");
    testBody.append(
      message.append(nestedListItem.append(gmailBody.append(selectedText))),
    );

    expect(
      findAnalysisRoot(asElement(selectedText), {
        hostname: "mail.google.com",
        maxTextLength: 8_000,
      }),
    ).toBe(asElement(message));
  });

  test("uses a Gmail list item when no message id is available", () => {
    const message = element("div", { role: "listitem" });
    const selectedText = element("span", {}, "Treść pojedynczej wiadomości.");
    testBody.append(message.append(selectedText));

    expect(
      findAnalysisRoot(asElement(selectedText), {
        hostname: "mail.google.com",
      }),
    ).toBe(asElement(message));
  });

  test("uses Outlook's document region instead of its labelled reading pane", () => {
    const readingPane = element("section", { "aria-label": "Reading pane" });
    const message = element("div", { role: "document" });
    const nestedArticle = element("article");
    const selectedText = element("span", {}, "Treść wiadomości z Outlooka.");
    testBody.append(
      readingPane.append(message.append(nestedArticle.append(selectedText))),
    );

    expect(
      findAnalysisRoot(asElement(selectedText), {
        hostname: "outlook.office.com",
      }),
    ).toBe(asElement(message));
  });

  test("chooses the innermost generic article, not the whole thread", () => {
    const thread = element("article");
    const message = element("article", { "aria-label": "Message" });
    const selectedText = element("span", {}, "Treść z uniwersalnego klienta poczty.");
    testBody.append(thread.append(message.append(selectedText)));

    expect(
      findAnalysisRoot(asElement(selectedText), { hostname: "mail.example.test" }),
    ).toBe(asElement(message));
  });

  test("prefers an explicitly declared analysis root over nested generic articles", () => {
    const explicitRoot = element("section", {
      "data-phishing-analysis-root": "",
    });
    const nestedArticle = element("article");
    const selectedText = element("span", {}, "Treść kontrolowanego playgroundu.");
    testBody.append(explicitRoot.append(nestedArticle.append(selectedText)));

    expect(
      findAnalysisRoot(asElement(selectedText), {
        hostname: "localhost",
      }),
    ).toBe(asElement(explicitRoot));
  });

  test("does not include collapsed sibling messages in the selected Gmail scope", () => {
    const thread = element("section", { "aria-label": "Conversation" });
    const collapsedMessage = element("div", {
      "aria-hidden": "true",
      "data-message-id": "collapsed",
    }, "q".repeat(101));
    const visibleMessage = element("div", { "data-message-id": "visible" });
    const visibleText = element("span", {}, "Aktualnie rozwinięta wiadomość.");
    testBody.append(
      thread.append(collapsedMessage, visibleMessage.append(visibleText)),
    );

    const root = findAnalysisRoot(asElement(visibleText), {
      hostname: "mail.google.com",
      maxTextLength: 100,
    });

    expect(root).toBe(asElement(visibleMessage));
    expect(root.textContent).not.toContain("q".repeat(20));
  });

  test("prefers a bounded message inside a thread whose total text is too large", () => {
    const thread = element("div", { role: "listitem" });
    const currentMessage = element("div", { "data-message-id": "current" });
    const selectedText = element("span", {}, "x".repeat(80));
    const quotedHistory = element("div", {}, "q".repeat(101));
    testBody.append(
      thread.append(currentMessage.append(selectedText), quotedHistory),
    );

    expect(
      findAnalysisRoot(asElement(selectedText), {
        hostname: "mail.google.com",
        maxTextLength: 100,
      }),
    ).toBe(asElement(currentMessage));
  });

  test("falls back below a generic thread when its only semantic boundary is too large", () => {
    const thread = element("article");
    const messageBody = element("div");
    const selectedText = element("span", {}, "x".repeat(60));
    const quotedHistory = element("div", {}, "q".repeat(101));
    testBody.append(thread.append(messageBody.append(selectedText), quotedHistory));

    expect(
      findAnalysisRoot(asElement(selectedText), {
        hostname: "mail.example.test",
        maxTextLength: 100,
      }),
    ).toBe(asElement(messageBody));
  });

  test("does not treat Gmail-only message ids as a generic page boundary", () => {
    const article = element("article");
    const gmailLookalike = element("div", { "data-message-id": "row-123" });
    const selectedText = element("span", {}, "Zwykły wpis na stronie.");
    testBody.append(article.append(gmailLookalike.append(selectedText)));

    expect(
      findAnalysisRoot(asElement(selectedText), {
        hostname: "app.example.test",
      }),
    ).toBe(asElement(article));
  });
});

describe("resolveAnalysisScope", () => {
  test("separates Gmail identity, analyzed content and safe hide target", () => {
    const message = element("div", { "data-message-id": "message-123" });
    const documentRoot = element("div", { role: "document" });
    const selectedText = element("span", {}, "Treść wiadomości Gmail.");
    testBody.append(message.append(documentRoot.append(selectedText)));

    const scope = resolveAnalysisScope(asElement(selectedText), {
      hostname: "mail.google.com",
    });

    expect(scope).toMatchObject({
      provider: "gmail",
      container: asElement(message),
      contentRoot: asElement(documentRoot),
      hideTarget: asElement(message),
      messageKey: "gmail:message-123",
      confidence: "strong",
      canAutoHide: true,
    });
  });

  test("updates the message key when Gmail reuses an element for another message", () => {
    const message = element("div", { "data-message-id": "message-one" });
    const selectedText = element("span", {}, "Pierwsza wiadomość.");
    testBody.append(message.append(selectedText));

    const first = resolveAnalysisScope(asElement(selectedText), {
      hostname: "mail.google.com",
    });
    message.setAttribute("data-message-id", "message-two");
    selectedText.textContent = "Druga wiadomość.";
    const second = resolveAnalysisScope(asElement(selectedText), {
      hostname: "mail.google.com",
    });

    expect(first.container).toBe(second.container);
    expect(first.messageKey).toBe("gmail:message-one");
    expect(second.messageKey).toBe("gmail:message-two");
  });

  test("chooses the nearest Gmail id when modern and legacy ids are nested", () => {
    const outerMessage = element("div", { "data-message-id": "outer" });
    const innerMessage = element("div", {
      "data-legacy-message-id": "inner",
    });
    const selectedText = element("span", {}, "Treść zagnieżdżonej wiadomości.");
    testBody.append(
      outerMessage.append(innerMessage.append(selectedText)),
    );

    const scope = resolveAnalysisScope(asElement(selectedText), {
      hostname: "mail.google.com",
    });

    expect(scope.container).toBe(asElement(innerMessage));
    expect(scope.messageKey).toBe("gmail:inner");
  });

  test("uses the stable legacy id when the same Gmail wrapper exposes both ids", () => {
    const message = element("div", {
      "data-message-id": "modern-wrapper-id",
      "data-legacy-message-id": "stable-message-id",
    });
    const selectedText = element("span", {}, "Treść wiadomości.");
    testBody.append(message.append(selectedText));

    const scope = resolveAnalysisScope(asElement(selectedText), {
      hostname: "mail.google.com",
    });

    expect(scope.container).toBe(asElement(message));
    expect(scope.messageKey).toBe("gmail:stable-message-id");
  });

  test("falls back to the modern Gmail id when the legacy attribute is empty", () => {
    const message = element("div", {
      "data-message-id": "modern-message-id",
      "data-legacy-message-id": "",
    });
    const selectedText = element("span", {}, "Treść wiadomości.");
    testBody.append(message.append(selectedText));

    const scope = resolveAnalysisScope(asElement(selectedText), {
      hostname: "mail.google.com",
    });

    expect(scope.messageKey).toBe("gmail:modern-message-id");
  });

  test("does not use document.body as a generic fallback boundary", () => {
    const selectedText = element("span", {}, "Samodzielny fragment treści.");
    testBody.append(selectedText);

    const scope = resolveAnalysisScope(asElement(selectedText), {
      hostname: "app.example.test",
    });

    expect(scope.container).toBe(asElement(selectedText));
    expect(scope.container).not.toBe(asElement(testBody));
    expect(scope.confidence).toBe("fallback");
    expect(scope.canAutoHide).toBe(false);
  });

  test("never auto-hides an Outlook document containing a visible editor", () => {
    const documentRoot = element("div", { role: "document" });
    const messageText = element("span", {}, "Podgląd wiadomości.");
    const replyEditor = element("div", { contenteditable: "true" }, "Odpowiedź");
    testBody.append(documentRoot.append(messageText, replyEditor));

    const scope = resolveAnalysisScope(asElement(messageText), {
      hostname: "outlook.office.com",
    });

    expect(scope.contentRoot).toBe(asElement(documentRoot));
    expect(scope.canAutoHide).toBe(false);
  });

  test("never auto-hides a Gmail wrapper containing a sibling reply editor", () => {
    const message = element("div", { "data-message-id": "message-123" });
    const documentRoot = element("div", { role: "document" });
    const messageText = element("span", {}, "Odebrana treść wiadomości.");
    const replyEditor = element(
      "div",
      { contenteditable: "true" },
      "Niewysłana odpowiedź użytkownika.",
    );
    testBody.append(
      message.append(documentRoot.append(messageText), replyEditor),
    );

    const scope = resolveAnalysisScope(asElement(messageText), {
      hostname: "mail.google.com",
    });

    expect(scope.contentRoot).toBe(asElement(documentRoot));
    expect(scope.hideTarget).toBe(asElement(message));
    expect(scope.canAutoHide).toBe(false);
  });

  test("never auto-hides a Gmail list item containing a sibling reply editor", () => {
    const mailbox = element("main", { role: "main" });
    const message = element("div", { role: "listitem" });
    const documentRoot = element("div", { role: "document" });
    const messageText = element("span", {}, "Odebrana treść wiadomości.");
    const replyEditor = element("div", { contenteditable: "true" }, "Szkic");
    testBody.append(
      mailbox.append(
        message.append(documentRoot.append(messageText), replyEditor),
      ),
    );

    const scope = resolveAnalysisScope(asElement(messageText), {
      hostname: "mail.google.com",
    });

    expect(scope.contentRoot).toBe(asElement(documentRoot));
    expect(scope.hideTarget).toBe(asElement(message));
    expect(scope.canAutoHide).toBe(false);
  });

  test("keeps generic semantic scopes analyzable but non-destructive", () => {
    const article = element("article");
    const messageText = element("span", {}, "Treść w nieznanym webmailu.");
    testBody.append(article.append(messageText));

    const scope = resolveAnalysisScope(asElement(messageText), {
      hostname: "mail.example.test",
    });

    expect(scope.confidence).toBe("medium");
    expect(scope.canAutoHide).toBe(false);
  });
});

describe("collectAnalysisScopes", () => {
  test("keeps a strong Gmail message analyzable and hideable despite its own checkbox", () => {
    const mailbox = element("main", { role: "main" });
    const message = element("div", { "data-message-id": "message-checkbox" });
    const checkbox = element("div", { role: "checkbox" });
    const messageText = element(
      "span",
      {},
      "Pilnie potwierdź dane logowania do banku.",
    );
    testBody.append(mailbox.append(message.append(checkbox, messageText)));

    const resolved = resolveAnalysisScope(asElement(messageText), {
      hostname: "mail.google.com",
    });
    const scopes = collectAnalysisScopes(asElement(testBody), {
      hostname: "mail.google.com",
    });

    expect(resolved.canAnalyze).toBe(true);
    expect(resolved.canAutoHide).toBe(true);
    expect(scopes).toHaveLength(1);
  });

  test("discovers a standalone Gmail message exposed only as a list item", () => {
    const mailbox = element("main", { role: "main" });
    const message = element("div", { role: "listitem" });
    const messageText = element("span", {}, "Treść wiadomości bez identyfikatora.");
    testBody.append(mailbox.append(message.append(messageText)));

    const scopes = collectAnalysisScopes(asElement(testBody), {
      hostname: "mail.google.com",
    });

    expect(scopes).toHaveLength(1);
    expect(scopes[0]).toMatchObject({
      provider: "gmail",
      container: asElement(message),
      contentRoot: asElement(message),
      hideTarget: asElement(message),
      confidence: "medium",
      canAutoHide: true,
    });
  });

  test("does not classify a Gmail inbox row as a message scope", () => {
    const grid = element("div", { role: "grid" });
    const inboxRow = element("div", { role: "listitem" });
    const rowText = element("span", {}, "Nadawca, temat i krótki podgląd.");
    testBody.append(grid.append(inboxRow.append(rowText)));

    const resolved = resolveAnalysisScope(asElement(rowText), {
      hostname: "mail.google.com",
    });
    const collected = collectAnalysisScopes(asElement(testBody), {
      hostname: "mail.google.com",
    });

    expect(resolved.container).toBe(asElement(inboxRow));
    expect(resolved.canAutoHide).toBe(false);
    expect(collected).toEqual([]);
  });

  test("does not classify a Gmail sidebar or chat list item as a message", () => {
    const sidebar = element("aside", { role: "complementary" });
    const chatItem = element("div", { role: "listitem" });
    const chatText = element("span", {}, "Kontakt i podgląd rozmowy na czacie.");
    testBody.append(sidebar.append(chatItem.append(chatText)));

    const resolved = resolveAnalysisScope(asElement(chatText), {
      hostname: "mail.google.com",
    });
    const collected = collectAnalysisScopes(asElement(testBody), {
      hostname: "mail.google.com",
    });

    expect(resolved.container).toBe(asElement(chatItem));
    expect(resolved.canAutoHide).toBe(false);
    expect(collected).toEqual([]);
  });

  test("does not trust a Gmail message id inside sidebar chrome", () => {
    const sidebar = element("aside", { role: "complementary" });
    const chatMessage = element("div", { "data-message-id": "chat-123" });
    const chatText = element("span", {}, "Treść modułu czatu.");
    testBody.append(sidebar.append(chatMessage.append(chatText)));

    const resolved = resolveAnalysisScope(asElement(chatText), {
      hostname: "mail.google.com",
    });
    const collected = collectAnalysisScopes(asElement(testBody), {
      hostname: "mail.google.com",
    });

    expect(resolved.container).toBe(asElement(chatMessage));
    expect(resolved.canAutoHide).toBe(false);
    expect(collected).toEqual([]);
  });

  test("uses a visible Gmail document when a hidden document precedes it", () => {
    const message = element("div", { "data-message-id": "message-123" });
    const collapsedDocument = element(
      "div",
      { role: "document", "aria-hidden": "true" },
      "Treść zwiniętej starszej wiadomości.",
    );
    const visibleDocument = element("div", { role: "document" });
    const currentText = element("span", {}, "Treść aktualnej wiadomości.");
    testBody.append(
      message.append(
        collapsedDocument,
        visibleDocument.append(currentText),
      ),
    );

    const scopes = collectAnalysisScopes(asElement(testBody), {
      hostname: "mail.google.com",
    });

    expect(scopes).toHaveLength(1);
    expect(scopes[0].container).toBe(asElement(message));
    expect(scopes[0].contentRoot).toBe(asElement(visibleDocument));
  });

  test("keeps read-only Gmail content analyzable beside a reply editor", () => {
    const message = element("div", { "data-message-id": "message-123" });
    const documentRoot = element("div", { role: "document" });
    const messageText = element(
      "span",
      {},
      "Pilnie potwierdź dane logowania w otrzymanej wiadomości.",
    );
    const replyEditor = element(
      "div",
      { contenteditable: "true" },
      "Szkic odpowiedzi.",
    );
    testBody.append(
      message.append(documentRoot.append(messageText), replyEditor),
    );

    const scopes = collectAnalysisScopes(asElement(testBody), {
      hostname: "mail.google.com",
    });

    expect(scopes).toHaveLength(1);
    expect(scopes[0].contentRoot).toBe(asElement(documentRoot));
    expect(scopes[0].canAnalyze).toBe(true);
    expect(scopes[0].canAutoHide).toBe(false);
  });

  test("analyzes a Gmail id wrapper without role=document while excluding auto-hide", () => {
    const message = element("div", { "data-message-id": "message-raw" });
    const messageText = element(
      "span",
      {},
      "URGENT ACTION: potwierdź dane logowania.",
    );
    const replyEditor = element(
      "div",
      { contenteditable: "true" },
      "Niewysłany szkic odpowiedzi.",
    );
    testBody.append(message.append(messageText, replyEditor));

    const resolved = resolveAnalysisScope(asElement(messageText), {
      hostname: "mail.google.com",
    });
    const scopes = collectAnalysisScopes(asElement(testBody), {
      hostname: "mail.google.com",
    });

    expect(resolved.contentRoot).toBe(asElement(message));
    expect(resolved.canAnalyze).toBe(true);
    expect(resolved.canAutoHide).toBe(false);
    expect(scopes).toHaveLength(1);
    expect(scopes[0].container).toBe(asElement(message));
  });
});
