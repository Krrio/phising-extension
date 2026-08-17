import { normalize } from "./normalize";
import { findNearestPhrase } from "./phrases";
import { getLinkRisk } from "./linkRisk";
import {
  isElementVisible,
  isInsideEditableOrControl,
  shouldSkipContentSubtree,
} from "./domVisibility";
import {
  getVisibleTextContentExcludingOwnUi,
  isInsideOwnUi,
} from "./ownUi";

const extensionMarks = new WeakSet<Element>();
interface LinkDecorationState {
  style: string | null;
  title: string | null;
  suspiciousAttribute: string | null;
}
const decoratedLinks = new WeakMap<HTMLAnchorElement, LinkDecorationState>();

export function isExtensionMark(
  element: Element | null,
): element is HTMLElement {
  return element instanceof HTMLElement && extensionMarks.has(element);
}

export function isExtensionDecoratedLink(
  element: Element,
): element is HTMLAnchorElement {
  return (
    element instanceof HTMLAnchorElement && decoratedLinks.has(element)
  );
}

export function highlightedNode(node: Node): void {
  const original = node.textContent ?? "";
  const { normalized, map } = normalize(original);
  let position = 0;
  let originalPosition = 0;
  const fragments: Node[] = [];
  let foundAnything = false;

  while (true) {
    const result = findNearestPhrase(normalized, position);
    if (result.phrase === null) {
      const rest = original.slice(originalPosition);
      if (rest) {
        fragments.push(document.createTextNode(rest));
      }
      break;
    }

    const start = result.position;
    const end = start + result.phrase.length;
    const originalStart = map[start];
    const originalEnd = map[end - 1] + 1;

    const before = original.slice(originalPosition, originalStart);
    if (before) {
      fragments.push(document.createTextNode(before));
    }

    const target = original.slice(originalStart, originalEnd);
    const mark = document.createElement("mark");
    extensionMarks.add(mark);
    mark.dataset.phishingMark = "true";
    mark.textContent = target;
    mark.style.backgroundImage = "linear-gradient(#dc2626, #dc2626)";
    mark.style.backgroundRepeat = "no-repeat";
    mark.style.backgroundPosition = "left bottom";
    mark.style.backgroundSize = "0% 2px";
    mark.style.transition = "background-size 0.3s ease";
    mark.style.paddingBottom = "1px";
    fragments.push(mark);

    foundAnything = true;
    position = end;
    originalPosition = originalEnd;
  }

  if (!foundAnything) {
    return;
  }

  const parent = node.parentElement;
  if (!parent) {
    return;
  }

  fragments.forEach((fragment) => {
    parent.insertBefore(fragment, node);
  });
  parent.removeChild(node);

  requestAnimationFrame(() => {
    fragments.forEach((fragment) => {
      if (fragment instanceof HTMLElement && fragment.dataset.phishingMark) {
        fragment.style.backgroundSize = "100% 2px";
      }
    });
  });
}

export function removeHighlights() {
  const marks = document.querySelectorAll("mark");
  for (const mark of Array.from(marks)) {
    if (!extensionMarks.has(mark)) continue;
    const parent = mark.parentNode;
    if (!parent) continue;
    const text = mark.textContent;
    const textNode = document.createTextNode(text ?? "");
    parent.insertBefore(textNode, mark);
    parent.removeChild(mark);
  }

  const suspiciousLinks = document.querySelectorAll("a");

  for (const link of Array.from(suspiciousLinks)) {
    if (link instanceof HTMLAnchorElement) restoreSuspiciousLink(link);
  }
}

function restoreAttribute(
  element: Element,
  name: string,
  originalValue: string | null,
): void {
  if (originalValue === null) element.removeAttribute(name);
  else element.setAttribute(name, originalValue);
}

function restoreSuspiciousLink(link: HTMLAnchorElement): void {
  const original = decoratedLinks.get(link);
  if (!original) return;

  decoratedLinks.delete(link);
  restoreAttribute(link, "style", original.style);
  restoreAttribute(link, "title", original.title);
  restoreAttribute(
    link,
    "data-phishing-suspicious-link",
    original.suspiciousAttribute,
  );
}

export function scanElement(root: Node): void {
  if (isInsideOwnUi(root)) return;

  if (
    root instanceof Element &&
    (!isElementVisible(root) || isInsideEditableOrControl(root))
  ) {
    return;
  }

  let currentNode: Node | null;
  const nodeArray: Node[] = [];
  const visibilityCache = new WeakMap<Element, boolean>();
  const treeWalker = document.createTreeWalker(
    root,
    NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        if (node.nodeType === Node.TEXT_NODE) return NodeFilter.FILTER_ACCEPT;

        const element = node as Element;
        if (
          (node !== root && isInsideOwnUi(element)) ||
          shouldSkipContentSubtree(element) ||
          isInsideEditableOrControl(element) ||
          !isElementVisible(element, null, visibilityCache)
        ) {
          return NodeFilter.FILTER_REJECT;
        }

        return NodeFilter.FILTER_SKIP;
      },
    },
  );
  while ((currentNode = treeWalker.nextNode()) != null) {
    if (currentNode.nodeType === Node.TEXT_NODE) nodeArray.push(currentNode);
  }
  nodeArray.forEach((node) => {
    const parent = node.parentElement;
    if (!parent) return;
    if (shouldSkipContentSubtree(parent)) return;
    const enclosingMark = parent.closest("mark[data-phishing-mark]");
    if (
      isInsideOwnUi(parent) ||
      isInsideEditableOrControl(parent) ||
      !isElementVisible(parent, null, visibilityCache) ||
      isExtensionMark(enclosingMark)
    ) {
      return;
    }
    highlightedNode(node);
  });
}

export function scanSuspiciousLinks(root: Element): void {
  if (isInsideOwnUi(root)) return;
  if (!isElementVisible(root) || isInsideEditableOrControl(root)) return;

  injectMarkStyle();

  const links = Array.from(root.querySelectorAll("a[href]")).filter(
    (link): link is HTMLAnchorElement => link instanceof HTMLAnchorElement,
  );

  if (root instanceof HTMLAnchorElement) {
    links.unshift(root);
  }

  for (const link of Array.from(new Set(links))) {
    if (isInsideOwnUi(link)) continue;

    if (!isElementVisible(link) || isInsideEditableOrControl(link)) {
      restoreSuspiciousLink(link);
      continue;
    }

    const risk = getLinkRisk(
      getVisibleTextContentExcludingOwnUi(link),
      link.href,
    );

    if (!risk.risky) {
      restoreSuspiciousLink(link);
      continue;
    }

    if (!decoratedLinks.has(link)) {
      decoratedLinks.set(link, {
        style: link.getAttribute("style"),
        title: link.getAttribute("title"),
        suspiciousAttribute: link.getAttribute(
          "data-phishing-suspicious-link",
        ),
      });
    }

    link.dataset.phishingSuspiciousLink = "true";
    link.style.backgroundImage = "linear-gradient(#dc2626, #dc2626)";
    link.style.backgroundRepeat = "no-repeat";
    link.style.backgroundPosition = "left bottom";
    link.style.backgroundSize = "0% 2px";
    link.style.transition = "background-size 0.3s ease";
    link.style.paddingBottom = "1px";
    link.title =
      risk.mismatch ?
        `Tekst linku nie zgadza się z celem: ${risk.hostname}`
      : `Podejrzana domena: ${risk.hostname}`;

    requestAnimationFrame(() => {
      if (decoratedLinks.has(link)) link.style.backgroundSize = "100% 2px";
    });
  }
}

export function injectMarkStyle() {
  const styleId = "pg-mark-style";

  if (document.getElementById(styleId)) return;

  const style = document.createElement("style");
  style.id = styleId;

  style.textContent = `
    mark[data-phishing-mark],
    a[data-phishing-suspicious-link] {
    cursor: pointer;
    background-color: transparent;
    transition: background-color 0.2s ease;
    }
    mark[data-phishing-mark]:hover,
    a[data-phishing-suspicious-link]:hover {
    background-color: rgba(220, 38, 38, 0.15);
    }
  `;
  document.head.appendChild(style);
}
