import { extractHostname, hasLinkMismatch } from "./links";
import { suspiciousWords } from "./phrases";
import { isSuspiciousDomain } from "./suspiciousDomain";

function collectLinks(element: Element): HTMLAnchorElement[] {
  const links = Array.from(element.querySelectorAll<HTMLAnchorElement>("a"));

  if (element instanceof HTMLAnchorElement) {
    links.unshift(element);
  }

  return Array.from(new Set(links));
}

export async function analyzeElement(element: Element) {
  const content = element.textContent ?? "";
  const foundPhrases = suspiciousWords.filter((phrase) =>
    content.includes(phrase),
  );

  const foundMismatches: { text: string; href: string }[] = [];
  const foundSuspiciousDomains = new Set<string>();
  const links = collectLinks(element);

  for (const link of links) {
    const text = link.textContent?.trim() ?? "";
    const href = link.href;

    if (hasLinkMismatch(text, href)) {
      foundMismatches.push({ text, href });
    }

    const hostname = extractHostname(href);
    if (hostname && isSuspiciousDomain(hostname)) {
      foundSuspiciousDomains.add(hostname);
    }
  }

  const payload = {
    content: content,
    signals: {
      suspiciousPhrases: foundPhrases,
      linkMismatches: foundMismatches,
      suspiciousDomains: Array.from(foundSuspiciousDomains),
    },
  };

  const answer = await fetch("http://localhost:8000/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return await answer.json();
}

export async function analyzeSelection(
  container: Element,
  range: Range,
  selectedText: string,
  phrases: string[],
) {
  const foundMismatches: { text: string; href: string }[] = [];
  const foundSuspiciousDomains = new Set<string>();
  const links = collectLinks(container);

  for (const link of links) {
    if (!range.intersectsNode(link)) {
      continue;
    }
    const text = link.textContent?.trim() ?? "";
    const href = link.href;
    if (hasLinkMismatch(text, href)) {
      foundMismatches.push({ text, href });
    }

    const hostname = extractHostname(href);
    if (hostname && isSuspiciousDomain(hostname)) {
      foundSuspiciousDomains.add(hostname);
    }
  }

  const payload = {
    content: selectedText,
    signals: {
      suspiciousPhrases: phrases,
      linkMismatches: foundMismatches,
      suspiciousDomains: Array.from(foundSuspiciousDomains),
    },
  };

  const answer = await fetch("http://localhost:8000/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return await answer.json();
}
