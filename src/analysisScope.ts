const SEMANTIC_ROOT_SELECTOR = [
  "[data-phishing-analysis-root]",
  "article",
  "[role='article']",
  "[role='document']",
].join(",");

const MAX_TEXT_LENGTH = 50_000;

export function findAnalysisRoot(start: Element): Element {
  const semanticRoot = start.closest<HTMLElement>(SEMANTIC_ROOT_SELECTOR);

  if (
    semanticRoot &&
    semanticRoot !== document.body &&
    (semanticRoot.textContent?.length ?? 0) <= MAX_TEXT_LENGTH
  ) {
    return semanticRoot;
  }

  let current = start.parentElement;
  let fallback: Element | null = null;

  while (current && current !== document.body) {
    const textLength = current.textContent?.trim().length ?? 0;

    if (textLength > MAX_TEXT_LENGTH) break;
    if (!fallback && textLength >= 40) fallback = current;
    if (current.querySelector("a[href]")) return current;

    current = current.parentElement;
  }

  return fallback ?? start.parentElement ?? start;
}
