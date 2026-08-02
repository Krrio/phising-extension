import { extractHostname } from "./links";
import type { AnalyzeResult, GuardianMessageResponse } from "./messages";
import { suspiciousWords } from "./phrases";
import { isSuspiciousDomain } from "./suspiciousDomain";
import { findAnalysisRoot } from "./analysisScope";

const STATUS_ID = "pg-guardian-status";
const MAX_CREW_CALLS_PER_PAGE = 3;
const SCAN_DEBOUNCE_MS = 3000;

const analyzedHashes = new Set<string>();
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

function isAnalyzableBlock(block: Element): boolean {
  if (block.closest(UI_NOISE_SELECTOR)) return false;
  if (
    block.closest("#pg-panel, #pg-guardian-status, #pg-suspicious-link-modal")
  )
    return false;

  const text = block.textContent?.trim() ?? "";
  return text.length >= 120;
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
    if (mark.closest("#pg-panel, #pg-guardian-status")) continue;
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

  return Array.from(candidates);
}

async function analyzeCandidate(block: Element): Promise<void> {
  const content = block.textContent?.trim() ?? "";
  if (content.length < 40) return;

  const hash = hashContent(content);
  if (analyzedHashes.has(hash)) return;
  if (crewCallCount >= MAX_CREW_CALLS_PER_PAGE) return;

  analyzedHashes.add(hash);
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
    console.log("[Guardian] werdykt dla bloku:", verdict, block);
    setGuardianStatus("active", "Guardian aktywny");
  } catch (error) {
    console.error("[Guardian] błąd analizy:", error);
    setGuardianStatus("error", "Guardian: błąd analizy");
  }
}

function setGuardianStatus(
  state: "active" | "scanning" | "error",
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
    : "#22c55e";
}

export function runGuardianScan(): void {
  if (!isGuardianActive) return;

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
