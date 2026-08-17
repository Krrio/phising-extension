import { getLinkRisk } from "./linkRisk";
import type {
  AnalyzeMessageResponse,
  AnalyzePayload,
  AnalyzeRequestMessage,
  AnalyzeResult,
} from "./messages";
import {
  getRangeTextExcludingOwnUi,
  getVisibleTextContentExcludingOwnUi,
  isInsideOwnUi,
} from "./ownUi";
import {
  isElementVisible,
  isInsideEditableOrControl,
} from "./domVisibility";
import { suspiciousWords } from "./phrases";

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
  const links = Array.from(element.querySelectorAll("a[href]")).filter(
    (link): link is HTMLAnchorElement => link instanceof HTMLAnchorElement,
  );

  if (element instanceof HTMLAnchorElement) {
    links.unshift(element);
  }

  return Array.from(new Set(links)).filter(
    (link) =>
      !isInsideOwnUi(link) &&
      isElementVisible(link) &&
      !isInsideEditableOrControl(link),
  );
}

export async function analyzeElement(element: Element): Promise<AnalyzeResult> {
  const content = getVisibleTextContentExcludingOwnUi(element);
  const normalizedContent = content.toLowerCase();
  const foundPhrases = suspiciousWords.filter((phrase) =>
    normalizedContent.includes(phrase.toLowerCase()),
  );

  const foundMismatches: AnalyzePayload["signals"]["linkMismatches"] = [];
  const foundSuspiciousDomains = new Set<string>();
  const links = collectLinks(element);

  for (const link of links) {
    const text = getVisibleTextContentExcludingOwnUi(link);
    const risk = getLinkRisk(text, link.href);

    if (risk.mismatch) {
      foundMismatches.push({ text, href: risk.effectiveHref });
    }

    if (risk.hostname && risk.suspiciousDomain) {
      foundSuspiciousDomains.add(risk.hostname);
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
  _selectedText: string,
  _phrases: string[],
): Promise<AnalyzeResult> {
  const content = getRangeTextExcludingOwnUi(container, range);
  const foundMismatches: AnalyzePayload["signals"]["linkMismatches"] = [];
  const foundSuspiciousDomains = new Set<string>();
  const links = collectLinks(container);

  for (const link of links) {
    if (!range.intersectsNode(link)) {
      continue;
    }
    const text = getVisibleTextContentExcludingOwnUi(link);
    const risk = getLinkRisk(text, link.href);
    if (risk.mismatch) {
      foundMismatches.push({ text, href: risk.effectiveHref });
    }

    if (risk.hostname && risk.suspiciousDomain) {
      foundSuspiciousDomains.add(risk.hostname);
    }
  }

  const payload: AnalyzePayload = {
    content,
    signals: {
      suspiciousPhrases: suspiciousWords.filter((phrase) =>
        content.toLowerCase().includes(phrase.toLowerCase()),
      ),
      linkMismatches: foundMismatches,
      suspiciousDomains: Array.from(foundSuspiciousDomains),
    },
  };

  return requestAnalysis(payload);
}
