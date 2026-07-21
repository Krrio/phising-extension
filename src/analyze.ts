import { extractHostname, hasLinkMismatch } from "./links";
import type {
  AnalyzeMessageResponse,
  AnalyzePayload,
  AnalyzeRequestMessage,
  AnalyzeResult,
} from "./messages";
import { suspiciousWords } from "./phrases";
import { isSuspiciousDomain } from "./suspiciousDomain";

async function requestAnalysis(payload: AnalyzePayload): Promise<AnalyzeResult> {
  const message: AnalyzeRequestMessage = { type: "ANALYZE", payload };
  const response = (await chrome.runtime.sendMessage(
    message,
  )) as AnalyzeMessageResponse;

  if (!response) {
    throw new Error("Service worker did not return a response.");
  }

  if (!response.ok) {
    throw new Error(response.error);
  }

  return response.data;
}

function collectLinks(element: Element): HTMLAnchorElement[] {
  const links = Array.from(element.querySelectorAll<HTMLAnchorElement>("a"));

  if (element instanceof HTMLAnchorElement) {
    links.unshift(element);
  }

  return Array.from(new Set(links));
}

export async function analyzeElement(element: Element): Promise<AnalyzeResult> {
  const content = element.textContent ?? "";
  const foundPhrases = suspiciousWords.filter((phrase) =>
    content.includes(phrase),
  );

  const foundMismatches: AnalyzePayload["signals"]["linkMismatches"] = [];
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

  const payload: AnalyzePayload = {
    content,
    signals: {
      suspiciousPhrases: foundPhrases,
      linkMismatches: foundMismatches,
      suspiciousDomains: Array.from(foundSuspiciousDomains),
    },
  };

  return requestAnalysis(payload);
}

export async function analyzeSelection(
  container: Element,
  range: Range,
  selectedText: string,
  phrases: string[],
): Promise<AnalyzeResult> {
  const foundMismatches: AnalyzePayload["signals"]["linkMismatches"] = [];
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

  const payload: AnalyzePayload = {
    content: selectedText,
    signals: {
      suspiciousPhrases: phrases,
      linkMismatches: foundMismatches,
      suspiciousDomains: Array.from(foundSuspiciousDomains),
    },
  };

  return requestAnalysis(payload);
}
