import {
  isGuardianOwnedHideMutation,
  runGuardianScan,
  startGuardian,
  stopGuardian,
} from "./agent";
import {
  collectAnalysisScopes,
  detectMailProvider,
  resolveAnalysisScope,
} from "./analysisScope";
import { analyzeElement } from "./analyze";
import { isElementVisible } from "./domVisibility";
import {
  isExtensionDecoratedLink,
  isExtensionMark,
  removeHighlights,
  scanElement,
  scanSuspiciousLinks,
} from "./highlight";
import { getLinkRisk } from "./linkRisk";
import { normalize } from "./normalize";
import {
  getVisibleTextContentExcludingOwnUi,
  isInsideOwnUi,
  registerOwnUiRoot,
} from "./ownUi";
import { findNearestPhrase, suspiciousWords } from "./phrases";
import {
  initSelectionListener,
  setSelectionAutoHighlightMode,
} from "./selection";
import { createWidget, injectPoppinsFont } from "./widget";

console.log("Phishing Extension content script loaded:", window.location.href);

let isFullScanActive = false;
let suspiciousLinkModal: HTMLElement | null = null;

function scanRiskIndicators(root: Node): void {
  const start =
    root instanceof Element ? root
    : root.parentElement ? root.parentElement
    : null;
  if (!start || isInsideOwnUi(start)) return;

  const targets = new Set<Element>();
  for (const scope of collectAnalysisScopes(start)) {
    targets.add(scope.contentRoot);
  }

  const containingScope = resolveAnalysisScope(start);
  if (
    containingScope.canAnalyze &&
    isElementVisible(containingScope.contentRoot)
  ) {
    targets.add(containingScope.contentRoot);
  }

  if (
    targets.size === 0 &&
    detectMailProvider(window.location.hostname) === "generic"
  ) {
    targets.add(start);
  }

  for (const target of targets) {
    scanElement(target);
    scanSuspiciousLinks(target);
  }
}

function analyzePage(): void {
  injectPoppinsFont();

  const scopes = collectAnalysisScopes(document);
  const roots = new Set<Element>(scopes.map((scope) => scope.contentRoot));
  if (
    roots.size === 0 &&
    detectMailProvider(window.location.hostname) === "generic"
  ) {
    roots.add(document.body);
  }

  const pageText = Array.from(roots)
    .map((root) => getVisibleTextContentExcludingOwnUi(root))
    .join(" ")
    .toLowerCase();

  const matches = suspiciousWords.filter((word) =>
    pageText.includes(word.toLowerCase()),
  );

  const score = matches.length;

  createWidget(score, matches);
  for (const root of roots) {
    scanElement(root);
    scanSuspiciousLinks(root);
  }

  console.log("Phishing analysis result:", {
    url: window.location.href,
    detectedMessageScopes: scopes.length,
    autoHideableScopes: scopes.filter((scope) => scope.canAutoHide).length,
    score,
    matches,
  });
}

function closeSuspiciousLinkModal(): void {
  suspiciousLinkModal?.remove();
  suspiciousLinkModal = null;
}

function createModalButton(label: string): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.style.border = "none";
  button.style.borderRadius = "999px";
  button.style.padding = "10px 16px";
  button.style.fontFamily = "Poppins, sans-serif";
  button.style.fontSize = "14px";
  button.style.fontWeight = "600";
  button.style.cursor = "pointer";
  return button;
}

function showSuspiciousLinkModal(
  href: string,
  hostname: string,
  mismatch: boolean,
): void {
  closeSuspiciousLinkModal();
  injectPoppinsFont();

  const overlay = document.createElement("div");
  registerOwnUiRoot(overlay);
  overlay.id = "pg-suspicious-link-modal";
  overlay.style.position = "fixed";
  overlay.style.inset = "0";
  overlay.style.zIndex = "2147483647";
  overlay.style.display = "grid";
  overlay.style.placeItems = "center";
  overlay.style.padding = "20px";
  overlay.style.background = "rgba(24, 24, 27, 0.48)";
  overlay.style.fontFamily = "Poppins, sans-serif";

  const dialog = document.createElement("div");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.style.width = "min(420px, 100%)";
  dialog.style.borderRadius = "18px";
  dialog.style.background = "#ffffff";
  dialog.style.color = "#18181b";
  dialog.style.boxShadow = "0 24px 80px rgba(0,0,0,0.28)";
  dialog.style.padding = "22px";

  const title = document.createElement("div");
  title.textContent = mismatch ? "Niezgodny adres linku" : "Podejrzana domena";
  title.style.fontSize = "20px";
  title.style.fontWeight = "700";
  title.style.marginBottom = "10px";
  dialog.appendChild(title);

  const message = document.createElement("p");
  message.textContent =
    mismatch ?
      "Tekst widoczny w wiadomości wskazuje inny serwis niż rzeczywisty adres docelowy. To częsta technika phishingowa. Czy na pewno chcesz otworzyć ten link?"
    : "Ta domena mocno przypomina znaną usługę i może prowadzić do phishingu. Czy na pewno chcesz ją otworzyć?";
  message.style.margin = "0 0 14px";
  message.style.color = "#3f3f46";
  message.style.fontSize = "14px";
  message.style.lineHeight = "1.5";
  dialog.appendChild(message);

  const domain = document.createElement("div");
  domain.textContent = hostname;
  domain.style.margin = "0 0 18px";
  domain.style.padding = "10px 12px";
  domain.style.borderRadius = "10px";
  domain.style.background = "#fef2f2";
  domain.style.color = "#991b1b";
  domain.style.fontSize = "13px";
  domain.style.fontWeight = "600";
  domain.style.overflowWrap = "anywhere";
  dialog.appendChild(domain);

  const actions = document.createElement("div");
  actions.style.display = "flex";
  actions.style.justifyContent = "flex-end";
  actions.style.gap = "10px";

  const cancelButton = createModalButton("Anuluj");
  cancelButton.style.background = "#e4e4e7";
  cancelButton.style.color = "#27272a";
  cancelButton.addEventListener("click", closeSuspiciousLinkModal);
  actions.appendChild(cancelButton);

  const confirmButton = createModalButton("Otwórz mimo ryzyka");
  confirmButton.style.background = "#dc2626";
  confirmButton.style.color = "#ffffff";
  confirmButton.addEventListener("click", () => {
    closeSuspiciousLinkModal();
    window.location.assign(href);
  });
  actions.appendChild(confirmButton);

  dialog.appendChild(actions);
  overlay.appendChild(dialog);

  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) {
      closeSuspiciousLinkModal();
    }
  });

  suspiciousLinkModal = overlay;
  document.body.appendChild(overlay);
  cancelButton.focus();
}

function handleSuspiciousLinkClick(event: MouseEvent): void {
  if (!isFullScanActive) return;
  if (event.defaultPrevented) return;
  if (event.button !== 0) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

  const target = event.target;
  if (!(target instanceof Element)) return;
  if (isInsideOwnUi(target)) return;

  const link = target.closest("a[href]");
  if (!(link instanceof HTMLAnchorElement)) return;

  const risk = getLinkRisk(
    getVisibleTextContentExcludingOwnUi(link),
    link.href,
  );
  if (!risk.risky || !risk.hostname) return;

  event.preventDefault();
  event.stopImmediatePropagation();
  showSuspiciousLinkModal(link.href, risk.hostname, risk.mismatch);
}

function startFullScan(): void {
  isFullScanActive = true;
  setSelectionAutoHighlightMode(true);
  observer.disconnect();
  try {
    analyzePage();
  } catch (error) {
    console.error("Phishing Guard: błąd skanowania początkowego", error);
  } finally {
    if (isFullScanActive) {
      observer.observe(document.body, observerOptions);
    }
  }
  runGuardianScan();
}

function stopFullScan(): void {
  isFullScanActive = false;
  setSelectionAutoHighlightMode(false);
  clearTimeout(debounceTimer);
  debounceTimer = undefined;
  pendingNodes.clear();
  closeSuspiciousLinkModal();
  observer.disconnect();
  removeHighlights();
}

async function syncFullScanFromStorage(): Promise<void> {
  const stored = await chrome.storage.local.get(["enabled", "autonomyLevel"]);
  const enabled = stored.enabled ?? true;

  if (!enabled) {
    stopFullScan();
    stopGuardian();
    return;
  }

  const level = (stored.autonomyLevel ?? "limited") as
    | "limited"
    | "standard"
    | "full"
    | "guardian";

  if (level === "full" || level === "guardian") {
    startFullScan();
  } else {
    stopFullScan();
  }

  if (level === "guardian") {
    startGuardian();
  } else {
    stopGuardian();
  }
}

async function init() {
  chrome.storage.onChanged.addListener((changes) => {
    if (changes.enabled || changes.autonomyLevel) {
      void syncFullScanFromStorage();
    }
  });

  await syncFullScanFromStorage();
}

const observerOptions: MutationObserverInit = {
  childList: true,
  subtree: true,
  characterData: true,
  attributes: true,
  attributeFilter: [
    "href",
    "hidden",
    "inert",
    "aria-hidden",
    "aria-expanded",
    "class",
    "style",
    "role",
    "contenteditable",
    "data-message-id",
    "data-legacy-message-id",
    "data-pg-hidden",
  ],
};

let debounceTimer: ReturnType<typeof setTimeout> | undefined;
const pendingNodes = new Set<Node>();

const observer = new MutationObserver((mutations) => {
  if (!isFullScanActive) return;

  let needsReconciliation = false;

  for (const mutation of mutations) {
    if (isInsideOwnUi(mutation.target)) continue;

    if (mutation.type === "childList") {
      if (mutation.removedNodes.length > 0) needsReconciliation = true;

      for (const addedNode of Array.from(mutation.addedNodes)) {
        if (isInsideOwnUi(addedNode)) continue;
        if (addedNode.nodeType === Node.ELEMENT_NODE) {
          pendingNodes.add(addedNode);
        } else if (addedNode.parentElement) {
          pendingNodes.add(addedNode.parentElement);
        }
      }
    }

    if (mutation.type === "characterData") {
      const parent = mutation.target.parentElement;
      if (parent) {
        pendingNodes.add(parent);
      }
    }

    if (mutation.type === "attributes" && mutation.target instanceof Element) {
      if (
        mutation.attributeName === "data-pg-hidden" &&
        isGuardianOwnedHideMutation(mutation.target)
      ) {
        continue;
      }
      if (
        mutation.attributeName === "style" &&
        (isExtensionMark(mutation.target) ||
          isExtensionDecoratedLink(mutation.target))
      ) {
        continue;
      }
      pendingNodes.add(mutation.target);
    }
  }

  if (pendingNodes.size === 0 && !needsReconciliation) return;

  if (debounceTimer !== undefined) return;

  debounceTimer = setTimeout(() => {
    debounceTimer = undefined;
    if (!isFullScanActive) {
      pendingNodes.clear();
      return;
    }

    const batch = Array.from(pendingNodes).filter(
      (node): node is Element => node instanceof Element && node.isConnected,
    );
    pendingNodes.clear();

    const roots = batch.filter(
      (node) =>
        !batch.some(
          (other) => other !== node && other.contains(node),
        ),
    );

    observer.disconnect();
    try {
      for (const root of roots) {
        try {
          scanRiskIndicators(root);
        } catch (error) {
          console.error("Phishing Guard: błąd skanowania DOM", error);
        }
      }
      runGuardianScan();
    } finally {
      if (isFullScanActive) {
        observer.observe(document.body, observerOptions);
      }
    }
  }, 300);
});

document.addEventListener("click", handleSuspiciousLinkClick, true);

init();
initSelectionListener();
