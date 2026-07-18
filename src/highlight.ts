import { normalize } from "./normalize";
import { findNearestPhrase } from "./phrases";
import { extractHostname } from "./links";
import { isSuspiciousDomain } from "./suspiciousDomain";

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
  const marks = document.querySelectorAll("mark[data-phishing-mark]");
  for (const mark of Array.from(marks)) {
    const parent = mark.parentNode;
    if (!parent) continue;
    const text = mark.textContent;
    const textNode = document.createTextNode(text ?? "");
    parent.insertBefore(textNode, mark);
    parent.removeChild(mark);
  }

  const suspiciousLinks = document.querySelectorAll(
    "a[data-phishing-suspicious-link]",
  );

  for (const link of Array.from(suspiciousLinks)) {
    const originalStyle = link.getAttribute("data-phishing-original-style");
    const originalTitle = link.getAttribute("data-phishing-original-title");

    link.removeAttribute("data-phishing-suspicious-link");
    link.removeAttribute("data-phishing-original-style");
    link.removeAttribute("data-phishing-original-title");

    if (originalStyle === null) {
      link.removeAttribute("style");
    } else {
      link.setAttribute("style", originalStyle);
    }

    if (originalTitle === null) {
      link.removeAttribute("title");
    } else {
      link.setAttribute("title", originalTitle);
    }
  }
}

export function scanElement(root: Node): void {
  const skippedElements = ["SCRIPT", "STYLE", "TEXTAREA"];
  let currentNode: Node | null;
  const nodeArray: Node[] = [];
  const treeWalker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while ((currentNode = treeWalker.nextNode()) != null) {
    nodeArray.push(currentNode);
  }
  nodeArray.forEach((node) => {
    const parent = node.parentElement;
    if (!parent) return;
    if (skippedElements.includes(parent.tagName)) return;
    if (parent.closest("#pg-panel") || parent.closest("#pg-selection-icon"))
      return;
    highlightedNode(node);
  });
}

export function scanSuspiciousLinks(root: Element): void {
  injectMarkStyle();

  const links = Array.from(root.querySelectorAll<HTMLAnchorElement>("a"));

  if (root instanceof HTMLAnchorElement) {
    links.unshift(root);
  }

  for (const link of Array.from(new Set(links))) {
    const hostname = extractHostname(link.href);

    if (!hostname || !isSuspiciousDomain(hostname)) {
      continue;
    }

    if (link.dataset.phishingSuspiciousLink !== "true") {
      const originalStyle = link.getAttribute("style");
      const originalTitle = link.getAttribute("title");

      if (originalStyle !== null) {
        link.dataset.phishingOriginalStyle = originalStyle;
      }

      if (originalTitle !== null) {
        link.dataset.phishingOriginalTitle = originalTitle;
      }
    }

    link.dataset.phishingSuspiciousLink = "true";
    link.style.backgroundImage = "linear-gradient(#dc2626, #dc2626)";
    link.style.backgroundRepeat = "no-repeat";
    link.style.backgroundPosition = "left bottom";
    link.style.backgroundSize = "0% 2px";
    link.style.transition = "background-size 0.3s ease";
    link.style.paddingBottom = "1px";
    link.title = `Podejrzana domena: ${hostname}`;

    requestAnimationFrame(() => {
      link.style.backgroundSize = "100% 2px";
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
