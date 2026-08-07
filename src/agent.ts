import { findAnalysisRoot } from "./analysisScope";
import { extractHostname } from "./links";
import type { AnalyzeResult, GuardianMessageResponse } from "./messages";
import { suspiciousWords } from "./phrases";
import { isSuspiciousDomain } from "./suspiciousDomain";

const STATUS_ID = "pg-guardian-status";
const MAX_CREW_CALLS_PER_PAGE = 3;
const SCAN_DEBOUNCE_MS = 3000;
const HIDDEN_ATTR = "data-pg-hidden";
const SHIELD_CLASS = "pg-guardian-shield";

const verdictCache = new Map<string, AnalyzeResult>();
const hiddenBlocks = new Map<Element, { hash: string; restore: () => void }>();
let crewCallCount = 0;
let scanTimer: ReturnType<typeof setTimeout> | undefined;
let isGuardianActive = false;

const UI_NOISE_SELECTOR = [
  "[role='status']",
  "[role='alert']",
  "[aria-live]",
  "nav",
  "header",
  "footer",
  "button",
].join(",");

const OWN_UI_SELECTOR =
  "#pg-panel, #pg-guardian-status, #pg-suspicious-link-modal, .pg-guardian-shield";

function isAnalyzableBlock(block: Element): boolean {
  if (block.closest(UI_NOISE_SELECTOR)) return false;
  if (block.closest(OWN_UI_SELECTOR)) return false;

  const text = block.textContent?.trim() ?? "";
  return text.length >= 120 && text.length <= 8000;
}

function hashContent(text: string): string {
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = (hash << 5) - hash + text.charCodeAt(i);
    hash |= 0;
  }
  return String(hash);
}

function collectCandidates(): Element[] {
  const candidates = new Set<Element>();

  const marks = document.querySelectorAll("mark[data-phishing-mark]");
  for (const mark of Array.from(marks)) {
    if (mark.closest(OWN_UI_SELECTOR)) continue;
    const block = findAnalysisRoot(mark);
    if (block && isAnalyzableBlock(block)) candidates.add(block);
  }

  const links = document.querySelectorAll<HTMLAnchorElement>("a[href]");
  for (const link of Array.from(links)) {
    const hostname = extractHostname(link.href);
    if (!hostname || !isSuspiciousDomain(hostname)) continue;
    const block = findAnalysisRoot(link);
    if (block && isAnalyzableBlock(block)) candidates.add(block);
  }

  const list = Array.from(candidates);
  return list.filter(
    (block) => !list.some((other) => other !== block && block.contains(other)),
  );
}

function shouldHide(verdict: AnalyzeResult): boolean {
  return (
    verdict.verdict === "phishing" &&
    verdict.trustScore < 30 &&
    verdict.confidence > 0.9
  );
}

function hideBlock(block: Element, verdict: AnalyzeResult, hash: string): void {
  if (!(block instanceof HTMLElement)) return;
  if (block.hasAttribute(HIDDEN_ATTR)) return;

  block.setAttribute(HIDDEN_ATTR, "true");
  const originalDisplay = block.style.display;

  const shield = document.createElement("div");
  shield.className = SHIELD_CLASS;
  shield.style.border = "2px solid #dc2626";
  shield.style.borderRadius = "12px";
  shield.style.padding = "18px";
  shield.style.margin = "8px 0";
  shield.style.background = "#fef2f2";
  shield.style.fontFamily = "Poppins, sans-serif";

  const title = document.createElement("div");
  title.textContent = "Treść ukryta przez Guardiana";
  title.style.fontWeight = "700";
  title.style.fontSize = "15px";
  title.style.color = "#991b1b";
  title.style.marginBottom = "8px";
  shield.appendChild(title);

  const reason = document.createElement("div");
  reason.textContent = verdict.reasoning;
  reason.style.fontSize = "13px";
  reason.style.color = "#7f1d1d";
  reason.style.lineHeight = "1.5";
  reason.style.marginBottom = "12px";
  shield.appendChild(reason);

  const score = document.createElement("div");
  score.textContent = `Trust score: ${verdict.trustScore}/100 · pewność ${Math.round(
    verdict.confidence * 100,
  )}%`;
  score.style.fontSize = "12px";
  score.style.color = "#b91c1c";
  score.style.marginBottom = "14px";
  shield.appendChild(score);

  const restore = () => {
    block.style.display = originalDisplay;
    block.removeAttribute(HIDDEN_ATTR);
    shield.remove();
    hiddenBlocks.delete(block);
  };

  const revealButton = document.createElement("button");
  revealButton.type = "button";
  revealButton.textContent = "Pokaż mimo to";
  revealButton.style.border = "none";
  revealButton.style.borderRadius = "999px";
  revealButton.style.padding = "9px 16px";
  revealButton.style.background = "#dc2626";
  revealButton.style.color = "white";
  revealButton.style.fontSize = "13px";
  revealButton.style.fontWeight = "600";
  revealButton.style.cursor = "pointer";
  revealButton.style.fontFamily = "Poppins, sans-serif";
  revealButton.addEventListener("click", restore);
  shield.appendChild(revealButton);

  block.style.display = "none";
  block.parentElement?.insertBefore(shield, block);

  hiddenBlocks.set(block, { hash, restore });
}

function releaseStaleBlocks(): void {
  for (const [block, entry] of Array.from(hiddenBlocks)) {
    if (!block.isConnected) {
      hiddenBlocks.delete(block);
      continue;
    }

    const currentHash = hashContent(block.textContent?.trim() ?? "");
    if (currentHash === entry.hash) continue;

    entry.restore();

    const cached = verdictCache.get(currentHash);
    if (cached && shouldHide(cached)) {
      hideBlock(block, cached, currentHash);
    }
  }
}

async function analyzeCandidate(block: Element): Promise<void> {
  const content = block.textContent?.trim() ?? "";
  if (content.length < 40) return;

  const hash = hashContent(content);

  const cached = verdictCache.get(hash);
  if (cached) {
    if (shouldHide(cached)) {
      hideBlock(block, cached, hash);
      setGuardianStatus("threat", "Guardian ukrył zagrożenie");
    }
    return;
  }

  if (crewCallCount >= MAX_CREW_CALLS_PER_PAGE) return;
  crewCallCount += 1;

  const phrases = suspiciousWords.filter((word) =>
    content.toLowerCase().includes(word.toLowerCase()),
  );

  const domains = new Set<string>();
  for (const link of Array.from(
    block.querySelectorAll<HTMLAnchorElement>("a[href]"),
  )) {
    const hostname = extractHostname(link.href);
    if (hostname && isSuspiciousDomain(hostname)) domains.add(hostname);
  }

  setGuardianStatus("scanning", "Guardian analizuje...");

  try {
    const verdict = await requestGuardianVerdict(
      content,
      Array.from(domains),
      phrases,
    );

    verdictCache.set(hash, verdict);

    if (shouldHide(verdict)) {
      hideBlock(block, verdict, hash);
      setGuardianStatus("threat", "Guardian ukrył zagrożenie");
    } else {
      setGuardianStatus("active", "Guardian aktywny");
    }
  } catch (error) {
    console.error("[Guardian] błąd analizy:", error);
    setGuardianStatus("error", "Guardian: błąd analizy");
  }
}

function setGuardianStatus(
  state: "active" | "scanning" | "error" | "threat",
  text: string,
): void {
  const panel = document.getElementById(STATUS_ID);
  if (!panel) return;

  const dot = panel.querySelector<HTMLElement>(".pg-guardian-dot");
  const label = panel.querySelector<HTMLElement>(".pg-guardian-label");
  if (!dot || !label) return;

  label.textContent = text;
  dot.style.background =
    state === "scanning" ? "#eab308"
    : state === "error" ? "#dc2626"
    : state === "threat" ? "#dc2626"
    : "#22c55e";
}

export function runGuardianScan(): void {
  if (!isGuardianActive) return;

  releaseStaleBlocks();

  clearTimeout(scanTimer);
  scanTimer = setTimeout(() => {
    const candidates = collectCandidates();
    for (const block of candidates) {
      void analyzeCandidate(block);
    }
  }, SCAN_DEBOUNCE_MS);
}

export function startGuardian(): void {
  isGuardianActive = true;

  if (document.getElementById(STATUS_ID)) return;

  const panel = document.createElement("div");
  panel.id = STATUS_ID;
  panel.style.position = "fixed";
  panel.style.bottom = "20px";
  panel.style.right = "20px";
  panel.style.zIndex = "2147483646";
  panel.style.display = "flex";
  panel.style.alignItems = "center";
  panel.style.gap = "10px";
  panel.style.padding = "10px 14px";
  panel.style.background = "#18181b";
  panel.style.color = "white";
  panel.style.borderRadius = "999px";
  panel.style.boxShadow = "0 8px 24px rgba(0,0,0,0.25)";
  panel.style.fontFamily = "Poppins, sans-serif";
  panel.style.fontSize = "13px";
  panel.style.opacity = "0";
  panel.style.transition = "opacity 0.3s ease";

  const dot = document.createElement("span");
  dot.className = "pg-guardian-dot";
  dot.style.width = "8px";
  dot.style.height = "8px";
  dot.style.borderRadius = "999px";
  dot.style.background = "#22c55e";
  dot.style.flexShrink = "0";
  panel.appendChild(dot);

  const label = document.createElement("span");
  label.className = "pg-guardian-label";
  label.textContent = "Guardian aktywny";
  panel.appendChild(label);

  document.body.appendChild(panel);
  requestAnimationFrame(() => {
    panel.style.opacity = "1";
  });
}

export function stopGuardian(): void {
  isGuardianActive = false;
  clearTimeout(scanTimer);
  crewCallCount = 0;

  for (const [, entry] of Array.from(hiddenBlocks)) {
    entry.restore();
  }
  hiddenBlocks.clear();

  const existing = document.getElementById(STATUS_ID);
  if (!existing) return;
  existing.style.opacity = "0";
  setTimeout(() => existing.remove(), 300);
}

async function requestGuardianVerdict(
  content: string,
  domains: string[],
  phrases: string[],
): Promise<AnalyzeResult> {
  const response = (await chrome.runtime.sendMessage({
    type: "GUARDIAN_ANALYZE",
    payload: { content, domains, phrases },
  })) as GuardianMessageResponse | undefined;

  if (!response) throw new Error("Brak odpowiedzi od Guardiana.");
  if (!response.ok) throw new Error(response.error);
  return response.data;
}
