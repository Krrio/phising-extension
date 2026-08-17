import {
  collectAnalysisScopes,
  resolveAnalysisScope,
  type AnalysisScope,
} from "./analysisScope";
import {
  appendGuardianAuditEntry,
  createGuardianAuditEntry,
} from "./guardianAudit";
import {
  isElementSelfHidden,
  isElementVisible,
  isInsideEditableOrControl,
} from "./domVisibility";
import {
  isExtensionDecoratedLink,
  isExtensionMark,
} from "./highlight";
import { getLinkRisk } from "./linkRisk";
import type { AnalyzeResult, GuardianMessageResponse } from "./messages";
import {
  getVisibleTextContentExcludingOwnUi,
  isInsideOwnUi,
  registerOwnUiRoot,
} from "./ownUi";
import { suspiciousWords } from "./phrases";
import { isSuspiciousDomain } from "./suspiciousDomain";
import { loadOrganizationPolicy } from "./organizationPolicy";

const STATUS_ID = "pg-guardian-status";
const MAX_CREW_CALLS_PER_WINDOW = 8;
const CREW_CALL_WINDOW_MS = 60_000;
const MAX_CONCURRENT_CALLS = 2;
const MAX_VERDICT_CACHE_ENTRIES = 100;
const MAX_ANALYSIS_CONTENT_LENGTH = 8_000;
const MIN_ANALYSIS_CONTENT_LENGTH = 1;
const MAX_LINK_MISMATCHES = 50;
const MAX_LINK_TEXT_LENGTH = 200;
const MAX_HREF_LENGTH = 2_048;
const ERROR_RETRY_COOLDOWN_MS = 60_000;
const SCAN_THROTTLE_MS = 750;
const HIDDEN_ATTR = "data-pg-hidden";
const SHIELD_CLASS = "pg-guardian-shield";
const HIDE_STYLE_ID = "pg-guardian-hide-style";
const HIDE_TOKEN = `pg-${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2)}`;
const NO_POLICY_REVISION = "none";

const verdictCache = new Map<string, AnalyzeResult>();
interface HiddenBlockEntry {
  fingerprint: string;
  messageKey: string;
  originalHiddenAttribute: string | null;
  scope: AnalysisScope;
  shield: HTMLElement;
  restore: () => void;
}

const hiddenBlocks = new Map<Element, HiddenBlockEntry>();
const revealedMessages = new Map<string, string>();
const inFlight = new Set<string>();
const failedUntil = new Map<string, number>();
const crewCallTimestamps: number[] = [];
let activeCrewCalls = 0;
let scanTimer: ReturnType<typeof setTimeout> | undefined;
let scanDueAt = Number.POSITIVE_INFINITY;
let isGuardianActive = false;
let statusPanel: HTMLElement | null = null;
let guardianGeneration = 0;
let hideStyle: HTMLStyleElement | null = null;
let organizationPolicyRevision: string | null = null;
let organizationPolicyFileName: string | null = null;
let policyLoadGeneration = 0;

export function isGuardianOwnedHideMutation(element: Element): boolean {
  return (
    hiddenBlocks.has(element) &&
    element.getAttribute(HIDDEN_ATTR) === HIDE_TOKEN
  );
}

const UI_NOISE_SELECTOR = [
  "[role='status']",
  "[role='alert']",
  "[aria-live]",
  "nav",
  "header",
  "footer",
  "button",
].join(",");

function isAnalyzableBlock(
  block: Element,
  guardianHiddenTarget: Element | null = null,
): boolean {
  if (block.matches(UI_NOISE_SELECTOR)) return false;
  if (isInsideOwnUi(block)) return false;
  if (isInsideEditableOrControl(block)) return false;
  const visible =
    guardianHiddenTarget &&
    guardianHiddenTarget.getAttribute(HIDDEN_ATTR) === HIDE_TOKEN &&
    (guardianHiddenTarget === block || guardianHiddenTarget.contains(block)) ?
      isVisibleWithinRoot(block, guardianHiddenTarget)
    : isElementVisible(block);
  if (!visible) return false;

  const text = getVisibleTextContentExcludingOwnUi(block, {
    ignoreRootVisibility:
      guardianHiddenTarget === block &&
      block.getAttribute(HIDDEN_ATTR) === HIDE_TOKEN,
  }).trim();
  return (
    text.length >= MIN_ANALYSIS_CONTENT_LENGTH ||
    block.querySelector("a[href]") !== null
  );
}

export function limitGuardianContent(
  content: string,
  maxLength = MAX_ANALYSIS_CONTENT_LENGTH,
): string {
  if (maxLength <= 0) return "";
  if (content.length <= maxLength) return content;

  const separator = "\n[… pominięto środkową część wiadomości …]\n";
  if (maxLength <= separator.length) return content.slice(0, maxLength);
  const available = Math.max(0, maxLength - separator.length);
  const beginningLength = Math.ceil(available * 0.6);
  const endingLength = available - beginningLength;

  return (
    content.slice(0, beginningLength).trimEnd() +
    separator +
    content.slice(-endingLength).trimStart()
  );
}

export interface GuardianFingerprintLink {
  text: string;
  href: string;
}

function compactHash(value: string): string {
  let h1 = 1_779_033_703;
  let h2 = 3_144_134_277;
  let h3 = 1_013_904_242;
  let h4 = 2_773_480_762;

  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    h1 = h2 ^ Math.imul(h1 ^ code, 597_399_067);
    h2 = h3 ^ Math.imul(h2 ^ code, 2_869_860_233);
    h3 = h4 ^ Math.imul(h3 ^ code, 951_274_213);
    h4 = h1 ^ Math.imul(h4 ^ code, 2_716_044_179);
  }

  h1 = Math.imul(h3 ^ (h1 >>> 18), 597_399_067);
  h2 = Math.imul(h4 ^ (h2 >>> 22), 2_869_860_233);
  h3 = Math.imul(h1 ^ (h3 >>> 17), 951_274_213);
  h4 = Math.imul(h2 ^ (h4 >>> 19), 2_716_044_179);

  return [h1, h2, h3, h4]
    .map((part) => (part >>> 0).toString(16).padStart(8, "0"))
    .join("");
}

function guardianLinkToken(
  link: string | GuardianFingerprintLink,
): string {
  const text =
    typeof link === "string" ? ""
    : canonicalizeFingerprintText(link.text);
  const href = typeof link === "string" ? link : link.href;
  return compactHash(`${text}\u0000${href}`);
}

function canonicalizeFingerprintText(value: string): string {
  return value
    .normalize("NFKC")
    .replace(/[\u200B-\u200D\uFEFF]/gu, "")
    .replace(/\s+/gu, " ")
    .trim();
}

function fingerprintFromLinkTokens(
  messageKey: string,
  content: string,
  linkTokens: string[],
  policyRevision: string,
): string {
  const normalizedTokens = Array.from(new Set(linkTokens)).sort();
  const canonicalContent = canonicalizeFingerprintText(content);
  const material = `${messageKey}\u0002${policyRevision}\u0002${canonicalContent}\u0002${normalizedTokens.join("\u0001")}`;
  return `v5:${canonicalContent.length}:${normalizedTokens.length}:${compactHash(material)}`;
}

export function createGuardianFingerprint(
  messageKey: string,
  content: string,
  links: Array<string | GuardianFingerprintLink>,
  policyRevision = NO_POLICY_REVISION,
): string {
  return fingerprintFromLinkTokens(
    messageKey,
    content,
    links.map(guardianLinkToken),
    policyRevision,
  );
}

function isVisibleWithinRoot(element: Element, root: Element): boolean {
  let current: Element | null = element;

  while (current) {
    const hiddenByGuardian =
      current === root && current.getAttribute(HIDDEN_ATTR) === HIDE_TOKEN;
    if (!hiddenByGuardian && isElementSelfHidden(current)) return false;
    if (current === root) return true;
    current = current.parentElement;
  }

  return false;
}

function visibleLinks(scope: AnalysisScope): HTMLAnchorElement[] {
  const links = Array.from(
    scope.contentRoot.querySelectorAll("a[href]"),
  ).filter(
    (link): link is HTMLAnchorElement => link instanceof HTMLAnchorElement,
  );
  if (scope.contentRoot instanceof HTMLAnchorElement) {
    links.unshift(scope.contentRoot);
  }

  return Array.from(new Set(links)).filter(
    (link) =>
      !isInsideOwnUi(link) &&
      !isInsideEditableOrControl(link, scope.contentRoot) &&
      isVisibleWithinRoot(link, scope.contentRoot),
  );
}

function scopeContent(scope: AnalysisScope): string {
  return getVisibleTextContentExcludingOwnUi(scope.contentRoot, {
    ignoreRootVisibility:
      scope.contentRoot.getAttribute(HIDDEN_ATTR) === HIDE_TOKEN,
  }).trim();
}

interface ScopeSnapshot {
  content: string;
  domains: string[];
  fingerprint: string;
  linkMismatches: Array<{ text: string; href: string }>;
  phrases: string[];
}

function snapshotScope(scope: AnalysisScope): ScopeSnapshot {
  const content = scopeContent(scope);
  const links = visibleLinks(scope);
  const domains = new Set<string>();
  const linkMismatches: ScopeSnapshot["linkMismatches"] = [];
  const fingerprintTokens: string[] = [];
  const riskyDomains = new Set<string>();
  const otherDomains = new Set<string>();

  for (const link of links) {
    const visibleText = getVisibleTextContentExcludingOwnUi(link);
    const risk = getLinkRisk(visibleText, link.href);
    const text = visibleText.slice(0, MAX_LINK_TEXT_LENGTH);
    const href = risk.effectiveHref.slice(0, MAX_HREF_LENGTH);
    fingerprintTokens.push(
      guardianLinkToken({ text: visibleText, href: risk.effectiveHref }),
    );

    if (risk.mismatch && linkMismatches.length < MAX_LINK_MISMATCHES) {
      linkMismatches.push({ text, href });
    }
    if (risk.hostname) {
      if (risk.risky) {
        riskyDomains.add(risk.hostname);
      } else {
        otherDomains.add(risk.hostname);
      }
    }
  }

  for (const hostname of [...riskyDomains, ...otherDomains]) {
    if (domains.size >= 20) break;
    domains.add(hostname);
  }

  const normalizedContent = content.toLowerCase();
  const phrases = suspiciousWords.filter((word) =>
    normalizedContent.includes(word.toLowerCase()),
  );

  return {
    content,
    domains: Array.from(domains),
    fingerprint: fingerprintFromLinkTokens(
      scope.messageKey,
      content,
      fingerprintTokens,
      organizationPolicyRevision ?? NO_POLICY_REVISION,
    ),
    linkMismatches,
    phrases,
  };
}

function hasLocalRisk(snapshot: ScopeSnapshot): boolean {
  return (
    snapshot.phrases.length > 0 ||
    snapshot.linkMismatches.length > 0 ||
    snapshot.domains.some((domain) => isSuspiciousDomain(domain))
  );
}

export function guardianRequiresLocalRisk(
  policyRevision: string | null,
): boolean {
  return (
    policyRevision === null || policyRevision === NO_POLICY_REVISION
  );
}

function collectCandidates(
  quarantinedScopes: AnalysisScope[] = [],
): AnalysisScope[] {
  const candidates = new Map<Element, AnalysisScope>();

  const addCandidate = (
    scope: AnalysisScope,
    requireLocalRisk: boolean,
    guardianHiddenTarget: Element | null = null,
  ) => {
    if (!isAnalyzableBlock(scope.contentRoot, guardianHiddenTarget)) return;
    if (requireLocalRisk && !hasLocalRisk(snapshotScope(scope))) return;
    candidates.set(scope.hideTarget, scope);
  };

  const requireLocalRisk = guardianRequiresLocalRisk(
    organizationPolicyRevision,
  );
  for (const scope of collectAnalysisScopes(document)) {
    // Without an organization policy, the local risk gate protects quota and
    // privacy. With a policy enabled, a message can violate an organization-
    // specific rule without matching any built-in phrase/domain heuristic, so
    // recognised mail scopes must reach the policy-aware analysis.
    addCandidate(scope, requireLocalRisk);
  }

  for (const scope of quarantinedScopes) {
    // A previously confirmed phishing message must be revalidated even when
    // Gmail temporarily removes the local phrase/link that first triggered it.
    addCandidate(scope, false, scope.hideTarget);
  }

  // A selection-triggered scan can already have produced trusted extension
  // indicators before a provider exposes a fully recognised message scope.
  // They may be analysed as a fallback, but a fallback scope can never hide
  // arbitrary page UI because `canAutoHide` remains false.
  for (const indicator of Array.from(
    document.querySelectorAll(
      "mark[data-phishing-mark],a[data-phishing-suspicious-link]",
    ),
  )) {
    const trusted =
      isExtensionMark(indicator) || isExtensionDecoratedLink(indicator);
    if (!trusted || !isElementVisible(indicator)) continue;
    if (
      Array.from(candidates.values()).some((scope) =>
        scope.contentRoot.contains(indicator),
      )
    ) {
      continue;
    }
    addCandidate(resolveAnalysisScope(indicator), true);
  }

  const scopes = Array.from(candidates.values());
  return scopes.filter(
    (scope) =>
      !scopes.some(
        (other) =>
          other !== scope && scope.hideTarget.contains(other.hideTarget),
      ),
  );
}

export type GuardianVerdictAction = "none" | "warn" | "hide";

export function getGuardianVerdictAction(
  verdict: AnalyzeResult,
): GuardianVerdictAction {
  if (verdict.verdict === "safe") return "none";
  if (
    verdict.verdict === "phishing" &&
    verdict.trustScore < 40 &&
    verdict.confidence >= 0.8
  ) {
    return "hide";
  }
  return "warn";
}

export interface HiddenBlockReconciliationInput {
  sameTarget: boolean;
  sameMessageKey: boolean;
  canAnalyze: boolean;
  canAutoHide: boolean;
  fingerprintMatches: boolean;
}

export type HiddenBlockReconciliation =
  | "keep"
  | "revalidate-hidden"
  | "restore";

export function getHiddenBlockReconciliation({
  sameTarget,
  sameMessageKey,
  canAnalyze,
  canAutoHide,
  fingerprintMatches,
}: HiddenBlockReconciliationInput): HiddenBlockReconciliation {
  if (!sameTarget || !sameMessageKey || !canAnalyze || !canAutoHide) {
    return "restore";
  }
  if (fingerprintMatches) return "keep";
  return "revalidate-hidden";
}

function ensureHideStyle(): void {
  if (hideStyle?.isConnected) return;

  const style = document.createElement("style");
  registerOwnUiRoot(style);
  style.id = HIDE_STYLE_ID;
  style.textContent = `[${HIDDEN_ATTR}="${HIDE_TOKEN}"] { display: none !important; }`;
  (document.head ?? document.documentElement).appendChild(style);
  hideStyle = style;
}

function rememberVerdict(fingerprint: string, verdict: AnalyzeResult): void {
  verdictCache.delete(fingerprint);
  verdictCache.set(fingerprint, verdict);

  while (verdictCache.size > MAX_VERDICT_CACHE_ENTRIES) {
    const oldest = verdictCache.keys().next().value as string | undefined;
    if (oldest === undefined) break;
    verdictCache.delete(oldest);
  }
}

function rememberReveal(messageKey: string, fingerprint: string): void {
  revealedMessages.delete(messageKey);
  revealedMessages.set(messageKey, fingerprint);

  while (revealedMessages.size > MAX_VERDICT_CACHE_ENTRIES) {
    const oldest = revealedMessages.keys().next().value as string | undefined;
    if (oldest === undefined) break;
    revealedMessages.delete(oldest);
  }
}

function hideBlock(
  scope: AnalysisScope,
  verdict: AnalyzeResult,
  snapshot: ScopeSnapshot,
  writeAudit = true,
): boolean {
  const block = scope.hideTarget;
  if (!(block instanceof HTMLElement)) return false;
  if (!scope.canAutoHide) return false;
  if (isInsideOwnUi(block)) return false;
  if (!block.isConnected || !block.parentElement) return false;
  const previous = hiddenBlocks.get(block);
  if (previous?.fingerprint === snapshot.fingerprint) return true;

  ensureHideStyle();

  const content = snapshot.content;
  const originalHiddenAttribute =
    previous?.originalHiddenAttribute ?? block.getAttribute(HIDDEN_ATTR);

  // Replace the shield without restoring the quarantined message between two
  // verdicts. This keeps changed phishing content from flashing on screen.
  if (previous) {
    previous.shield.remove();
    hiddenBlocks.delete(block);
  }

  const shield = document.createElement("div");
  registerOwnUiRoot(shield);
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

  if (
    verdict.policyAssessment &&
    (verdict.policyAssessment.violated ||
      verdict.policyAssessment.influence !== "none")
  ) {
    const policy = document.createElement("div");
    policy.style.fontSize = "12px";
    policy.style.lineHeight = "1.45";
    policy.style.color = "#9a3412";
    policy.style.background = "#ffedd5";
    policy.style.borderRadius = "8px";
    policy.style.padding = "8px 10px";
    policy.style.marginBottom = "14px";
    policy.textContent = `Polityka ${verdict.policyAssessment.policyFileName} wpłynęła na decyzję${
      verdict.policyAssessment.summary ?
        `: ${verdict.policyAssessment.summary}`
      : "."
    }`;
    shield.appendChild(policy);
  }

  const restore = () => {
    const current = hiddenBlocks.get(block);
    if (current && current.shield !== shield) {
      shield.remove();
      return;
    }
    if (block.getAttribute(HIDDEN_ATTR) === HIDE_TOKEN) {
      if (originalHiddenAttribute === null) {
        block.removeAttribute(HIDDEN_ATTR);
      } else {
        block.setAttribute(HIDDEN_ATTR, originalHiddenAttribute);
      }
    }
    shield.remove();
    if (hiddenBlocks.get(block)?.shield === shield) {
      hiddenBlocks.delete(block);
    }
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
  revealButton.addEventListener("click", () => {
    try {
      const currentSeed =
        scope.contentRoot.isConnected ? scope.contentRoot : block;
      const currentScope = resolveAnalysisScope(currentSeed);
      const currentSnapshot = snapshotScope(currentScope);
      rememberReveal(currentScope.messageKey, currentSnapshot.fingerprint);
    } catch {
      rememberReveal(scope.messageKey, snapshot.fingerprint);
    }
    restore();
    void appendGuardianAuditEntry(
      createGuardianAuditEntry(
        "revealed",
        verdict,
        content,
        window.location.href,
      ),
    );
  });
  shield.appendChild(revealButton);

  block.parentElement.insertBefore(shield, block);
  block.setAttribute(HIDDEN_ATTR, HIDE_TOKEN);

  hiddenBlocks.set(block, {
    fingerprint: snapshot.fingerprint,
    messageKey: scope.messageKey,
    originalHiddenAttribute,
    scope,
    shield,
    restore,
  });
  if (writeAudit && !previous) {
    void appendGuardianAuditEntry(
      createGuardianAuditEntry(
        "hidden",
        verdict,
        content,
        window.location.href,
      ),
    );
  }
  return true;
}

function applyGuardianVerdict(
  scope: AnalysisScope,
  verdict: AnalyzeResult,
  snapshot: ScopeSnapshot,
): void {
  const action = getGuardianVerdictAction(verdict);
  const existing = hiddenBlocks.get(scope.hideTarget);
  const policySignal =
    verdict.policyAssessment?.violated ? " · naruszenie polityki" : "";

  if (action === "hide") {
    const hidden = scope.canAutoHide && hideBlock(scope, verdict, snapshot);
    if (!hidden) existing?.restore();
    setGuardianStatus(
      "threat",
      hidden ?
        `Guardian zablokował phishing${policySignal}`
      : `Guardian wykrył phishing — mail pozostawiony${policySignal}`,
      verdict.reasoning,
    );
    return;
  }

  existing?.restore();

  if (action === "warn") {
    setGuardianStatus(
      "warning",
      `Podejrzany mail${policySignal} · ${verdict.trustScore}/100`,
      verdict.reasoning,
    );
    return;
  }

  // The scan scheduler restores the neutral state. A safe result must not
  // overwrite a warning produced by another concurrent candidate.
}

function withoutGuardianHideRule<T>(operation: () => T): T {
  const sheet = hideStyle?.sheet;
  if (!sheet) return operation();

  const wasDisabled = sheet.disabled;
  sheet.disabled = true;
  try {
    return operation();
  } finally {
    sheet.disabled = wasDisabled;
  }
}

function releaseStaleBlocks(): AnalysisScope[] {
  const quarantinedScopes: AnalysisScope[] = [];

  for (const [block, entry] of Array.from(hiddenBlocks)) {
    if (!block.isConnected) {
      entry.restore();
      continue;
    }

    const seed =
      entry.scope.contentRoot.isConnected ? entry.scope.contentRoot : block;
    const reconciled = withoutGuardianHideRule(() => {
      const currentScope = resolveAnalysisScope(seed);
      if (!isElementVisible(currentScope.contentRoot)) return null;
      return {
        currentScope,
        currentSnapshot: snapshotScope(currentScope),
      };
    });
    if (!reconciled) {
      entry.restore();
      continue;
    }

    const { currentScope, currentSnapshot } = reconciled;
    const reconciliation = getHiddenBlockReconciliation({
      sameTarget: currentScope.hideTarget === block,
      sameMessageKey: currentScope.messageKey === entry.messageKey,
      canAnalyze: currentScope.canAnalyze,
      canAutoHide: currentScope.canAutoHide,
      fingerprintMatches:
        currentSnapshot.fingerprint === entry.fingerprint,
    });
    if (reconciliation === "restore") {
      entry.restore();
      continue;
    }

    // Gmail may insert harmless text/comment nodes or temporarily detach our
    // shield while reconciling its SPA tree. Repair the quarantine in place
    // instead of exposing the message and starting the lifecycle again.
    ensureHideStyle();
    if (!block.parentElement) {
      entry.restore();
      continue;
    }
    if (
      entry.shield.parentElement !== block.parentElement ||
      entry.shield.nextElementSibling !== block
    ) {
      block.parentElement.insertBefore(entry.shield, block);
    }
    if (block.getAttribute(HIDDEN_ATTR) !== HIDE_TOKEN) {
      block.setAttribute(HIDDEN_ATTR, HIDE_TOKEN);
    }

    entry.scope = currentScope;
    if (reconciliation === "keep") continue;

    // Keep the previous phishing verdict visible as a shield while the
    // changed content is revalidated. The new verdict decides whether to
    // update the shield or restore the message.
    quarantinedScopes.push(currentScope);
  }

  return quarantinedScopes;
}

function pruneCrewCallWindow(now = Date.now()): void {
  while (
    crewCallTimestamps.length > 0 &&
    now - crewCallTimestamps[0] >= CREW_CALL_WINDOW_MS
  ) {
    crewCallTimestamps.shift();
  }
}

function nextRateLimitDelay(now = Date.now()): number {
  pruneCrewCallWindow(now);
  if (crewCallTimestamps.length < MAX_CREW_CALLS_PER_WINDOW) {
    return SCAN_THROTTLE_MS;
  }
  return Math.max(
    SCAN_THROTTLE_MS,
    crewCallTimestamps[0] + CREW_CALL_WINDOW_MS - now + 50,
  );
}

function crewCallBlockReason(): "concurrency" | "rate" | null {
  const now = Date.now();
  pruneCrewCallWindow(now);
  if (activeCrewCalls >= MAX_CONCURRENT_CALLS) return "concurrency";
  if (crewCallTimestamps.length >= MAX_CREW_CALLS_PER_WINDOW) return "rate";
  return null;
}

function reserveCrewCall(): void {
  activeCrewCalls += 1;
  crewCallTimestamps.push(Date.now());
}

function rememberFailure(fingerprint: string): void {
  failedUntil.delete(fingerprint);
  failedUntil.set(fingerprint, Date.now() + ERROR_RETRY_COOLDOWN_MS);

  while (failedUntil.size > MAX_VERDICT_CACHE_ENTRIES) {
    const oldest = failedUntil.keys().next().value as string | undefined;
    if (oldest === undefined) break;
    failedUntil.delete(oldest);
  }
}

function restoreHiddenBlockForMessage(
  block: Element,
  messageKey: string,
): void {
  const entry = hiddenBlocks.get(block);
  if (entry?.messageKey === messageKey) entry.restore();
}

async function analyzeCandidate(scope: AnalysisScope): Promise<void> {
  const block = scope.hideTarget;
  if (isInsideOwnUi(block)) return;

  const snapshot = snapshotScope(scope);
  if (
    snapshot.content.length < MIN_ANALYSIS_CONTENT_LENGTH &&
    snapshot.domains.length === 0 &&
    snapshot.linkMismatches.length === 0
  ) {
    return;
  }
  if (revealedMessages.get(scope.messageKey) === snapshot.fingerprint) return;

  const retryAt = failedUntil.get(snapshot.fingerprint);
  if (retryAt !== undefined) {
    if (retryAt > Date.now()) {
      scheduleGuardianScan(retryAt - Date.now() + 50);
      return;
    }
    failedUntil.delete(snapshot.fingerprint);
  }

  const cached = verdictCache.get(snapshot.fingerprint);
  if (cached) {
    applyGuardianVerdict(scope, cached, snapshot);
    return;
  }

  if (inFlight.has(snapshot.fingerprint)) return;
  const blockReason = crewCallBlockReason();
  if (blockReason === "concurrency") return;
  if (blockReason === "rate") {
    scheduleGuardianScan(nextRateLimitDelay());
    return;
  }

  reserveCrewCall();
  const generation = guardianGeneration;
  inFlight.add(snapshot.fingerprint);
  setGuardianStatus("scanning", "Guardian analizuje...");

  try {
    const verdict = await requestGuardianVerdict(
      limitGuardianContent(snapshot.content),
      snapshot.domains,
      snapshot.phrases,
      snapshot.linkMismatches,
    );

    if (!isGuardianActive || generation !== guardianGeneration) return;
    const verdictPolicyRevision =
      verdict.policyAssessment?.policyHash ?? NO_POLICY_REVISION;
    if (verdictPolicyRevision !== organizationPolicyRevision) {
      // Background always binds the verdict to the policy snapshot it used.
      // If storage changed while the request was running, refresh identity and
      // re-run instead of applying an obsolete organizational decision.
      void refreshOrganizationPolicyContext();
      return;
    }
    rememberVerdict(snapshot.fingerprint, verdict);

    if (!block.isConnected) return;
    const currentSeed = scope.contentRoot.isConnected ? scope.contentRoot : block;
    const currentScope = resolveAnalysisScope(currentSeed);
    const currentSnapshot = snapshotScope(currentScope);
    const quarantinedTarget = hiddenBlocks.has(block) ? block : null;
    if (
      currentScope.hideTarget !== block ||
      currentScope.messageKey !== scope.messageKey ||
      !currentScope.canAnalyze ||
      !isAnalyzableBlock(currentScope.contentRoot, quarantinedTarget)
    ) {
      restoreHiddenBlockForMessage(block, scope.messageKey);
      runGuardianScan();
      return;
    }

    if (quarantinedTarget && !currentScope.canAutoHide) {
      restoreHiddenBlockForMessage(block, scope.messageKey);
      runGuardianScan();
      return;
    }

    if (currentSnapshot.fingerprint !== snapshot.fingerprint) {
      // The SPA changed the message again while the request was in flight.
      // Keep the old shield and validate the latest snapshot next.
      runGuardianScan();
      return;
    }

    if (
      revealedMessages.get(currentScope.messageKey) ===
      currentSnapshot.fingerprint
    ) {
      hiddenBlocks.get(block)?.restore();
      return;
    }

    applyGuardianVerdict(currentScope, verdict, currentSnapshot);
  } catch (error) {
    if (!isGuardianActive || generation !== guardianGeneration) return;
    rememberFailure(snapshot.fingerprint);
    console.error("[Guardian] błąd analizy:", error);
    setGuardianStatus("error", "Guardian: błąd analizy");
  } finally {
    inFlight.delete(snapshot.fingerprint);
    activeCrewCalls = Math.max(0, activeCrewCalls - 1);
    if (isGuardianActive) runGuardianScan();
  }
}

function setGuardianStatus(
  state: "active" | "scanning" | "warning" | "error" | "threat",
  text: string,
  details = "",
): void {
  const panel = statusPanel;
  if (!panel) return;

  const dot = panel.querySelector<HTMLElement>(".pg-guardian-dot");
  const label = panel.querySelector<HTMLElement>(".pg-guardian-label");
  if (!dot || !label) return;

  const policySuffix =
    organizationPolicyFileName ?
      ` · polityka: ${shortPolicyName(organizationPolicyFileName)}`
    : "";
  label.textContent = `${text}${policySuffix}`;
  panel.title = details;
  dot.style.background =
    state === "scanning" ? "#eab308"
    : state === "warning" ? "#f59e0b"
    : state === "error" ? "#dc2626"
    : state === "threat" ? "#dc2626"
    : "#22c55e";
}

function scheduleGuardianScan(delay = SCAN_THROTTLE_MS): void {
  if (!isGuardianActive || organizationPolicyRevision === null) return;

  const dueAt = Date.now() + Math.max(0, delay);
  if (scanTimer !== undefined && scanDueAt <= dueAt) return;

  clearTimeout(scanTimer);
  scanDueAt = dueAt;

  scanTimer = setTimeout(() => {
    scanTimer = undefined;
    scanDueAt = Number.POSITIVE_INFINITY;
    if (!isGuardianActive) return;

    const quarantinedScopes = releaseStaleBlocks();
    const candidates = collectCandidates(quarantinedScopes);
    if (hiddenBlocks.size === 0 && inFlight.size === 0) {
      setGuardianStatus("active", "Guardian aktywny");
    }
    for (const scope of candidates) {
      void analyzeCandidate(scope);
    }
  }, delay);
}

export function runGuardianScan(): void {
  if (!isGuardianActive || organizationPolicyRevision === null) return;
  scheduleGuardianScan();
}

function shortPolicyName(fileName: string): string {
  const compact = fileName.replace(/\s+/g, " ").trim();
  return compact.length <= 28 ? compact : `${compact.slice(0, 27)}…`;
}

async function refreshOrganizationPolicyContext(): Promise<void> {
  const loadGeneration = ++policyLoadGeneration;

  try {
    const policy = await loadOrganizationPolicy();
    if (
      loadGeneration !== policyLoadGeneration ||
      !isGuardianActive
    ) {
      return;
    }

    const nextRevision = policy?.contentHash ?? NO_POLICY_REVISION;
    const previousRevision = organizationPolicyRevision;
    organizationPolicyRevision = nextRevision;
    organizationPolicyFileName = policy?.fileName ?? null;

    if (
      previousRevision !== null &&
      previousRevision !== nextRevision
    ) {
      // Policy is part of the security identity. Old cache entries, cooldowns,
      // reveals and in-flight responses cannot cross policy revisions.
      guardianGeneration += 1;
      verdictCache.clear();
      failedUntil.clear();
      revealedMessages.clear();
    }

    if (hiddenBlocks.size === 0 && inFlight.size === 0) {
      setGuardianStatus("active", "Guardian aktywny");
    }
    scheduleGuardianScan(0);
  } catch (error) {
    if (loadGeneration !== policyLoadGeneration || !isGuardianActive) return;
    console.error("[Guardian] nie udało się wczytać polityki:", error);
    // Fail closed for already quarantined phishing: keep its shield (which
    // still offers "Pokaż mimo to"), stop new remote decisions, and expose a
    // recoverable error. The popup can replace or remove the invalid record.
    setGuardianStatus(
      "error",
      "Guardian: błąd polityki",
      "Zastąp lub usuń uszkodzoną politykę w popupie rozszerzenia.",
    );
  }
}

export function handleOrganizationPolicyChange(_newValue: unknown): void {
  // Any write is invalidated synchronously, before async hash verification.
  // A structurally valid record can still contain content that does not match
  // its declared SHA-256; retaining the previous revision even briefly would
  // let an old in-flight result cross that storage boundary.
  guardianGeneration += 1;
  policyLoadGeneration += 1;
  verdictCache.clear();
  failedUntil.clear();
  revealedMessages.clear();
  organizationPolicyRevision = null;
  organizationPolicyFileName = null;
  clearTimeout(scanTimer);
  scanTimer = undefined;
  scanDueAt = Number.POSITIVE_INFINITY;
  if (!isGuardianActive) return;
  void refreshOrganizationPolicyContext();
}

export function startGuardian(): void {
  if (!isGuardianActive) guardianGeneration += 1;
  isGuardianActive = true;

  if (statusPanel?.isConnected) {
    void refreshOrganizationPolicyContext();
    return;
  }

  const panel = document.createElement("div");
  registerOwnUiRoot(panel);
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
  label.textContent = "Guardian wczytuje politykę…";
  panel.appendChild(label);

  const killButton = document.createElement("button");
  killButton.type = "button";
  killButton.textContent = "Wyłącz";
  killButton.style.border = "none";
  killButton.style.borderRadius = "999px";
  killButton.style.padding = "5px 12px";
  killButton.style.marginLeft = "4px";
  killButton.style.background = "#3f3f46";
  killButton.style.color = "white";
  killButton.style.fontSize = "12px";
  killButton.style.fontWeight = "600";
  killButton.style.cursor = "pointer";
  killButton.style.fontFamily = "Poppins, sans-serif";
  killButton.addEventListener("click", () => {
    void killGuardian();
  });
  panel.appendChild(killButton);

  statusPanel = panel;
  document.body.appendChild(panel);
  requestAnimationFrame(() => {
    panel.style.opacity = "1";
  });
  void refreshOrganizationPolicyContext();
}

export function stopGuardian(): void {
  isGuardianActive = false;
  guardianGeneration += 1;
  policyLoadGeneration += 1;
  organizationPolicyRevision = null;
  organizationPolicyFileName = null;
  clearTimeout(scanTimer);
  scanTimer = undefined;
  scanDueAt = Number.POSITIVE_INFINITY;
  crewCallTimestamps.length = 0;
  failedUntil.clear();

  for (const [, entry] of Array.from(hiddenBlocks)) {
    entry.restore();
  }
  hiddenBlocks.clear();
  revealedMessages.clear();
  hideStyle?.remove();
  hideStyle = null;

  const existing = statusPanel;
  if (!existing) return;
  statusPanel = null;
  existing.style.opacity = "0";
  setTimeout(() => existing.remove(), 300);
}

export async function killGuardian(): Promise<void> {
  stopGuardian();
  await chrome.storage.local.set({ autonomyLevel: "full" });
}

async function requestGuardianVerdict(
  content: string,
  domains: string[],
  phrases: string[],
  linkMismatches: Array<{ text: string; href: string }>,
): Promise<AnalyzeResult> {
  const response = (await chrome.runtime.sendMessage({
    type: "GUARDIAN_ANALYZE",
    payload: { content, domains, phrases, linkMismatches },
  })) as GuardianMessageResponse | undefined;

  if (!response) throw new Error("Brak odpowiedzi od Guardiana.");
  if (!response.ok) throw new Error(response.error);
  return response.data;
}
