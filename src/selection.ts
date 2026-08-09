import { findAnalysisRoot } from "./analysisScope";
import { analyzeElement, analyzeSelection } from "./analyze";
import {
  injectMarkStyle,
  removeHighlights,
  scanElement,
  scanSuspiciousLinks,
} from "./highlight";
import {
  getRangeTextExcludingOwnUi,
  getTextContentExcludingOwnUi,
  isInsideOwnUi,
  registerOwnUiRoot,
} from "./ownUi";
import { suspiciousWords } from "./phrases";
import { renderResult } from "./results";
import { injectPoppinsFont } from "./widget";

let lastSelectedText = "";
let lastCount = 0;
let lastPhrases: string[] = [];
let lastRange: Range | null = null;
let lastContainer: Element | null = null;
let lastAnalysisRoot: Element | null = null;
let selectionIcon: HTMLElement | null = null;
let selectionPanel: HTMLElement | null = null;

function injectSpinnerStyle() {
  const styleId = "pg-spinner-style";
  if (document.getElementById(styleId)) return;

  const style = document.createElement("style");
  style.id = styleId;
  style.textContent = `
    @keyframes pg-spin {
      to { transform: rotate(360deg); }
    }
  `;
  document.head.appendChild(style);
}

function createSpinner(): HTMLElement {
  injectSpinnerStyle();

  const spinner = document.createElement("div");
  spinner.style.width = "20px";
  spinner.style.height = "20px";
  spinner.style.border = "3px solid rgba(255,255,255,0.4)";
  spinner.style.borderTopColor = "white";
  spinner.style.borderRadius = "50%";
  spinner.style.animation = "pg-spin 0.6s linear infinite";
  spinner.style.margin = "0 auto";
  return spinner;
}

function createIcon(): HTMLElement {
  const iconDiv = document.createElement("div");
  registerOwnUiRoot(iconDiv);
  iconDiv.id = "pg-selection-icon";
  iconDiv.style.width = "24px";
  iconDiv.style.height = "24px";
  iconDiv.style.borderRadius = "999px";
  iconDiv.style.background = "#7c3aed";
  iconDiv.style.display = "flex";
  iconDiv.style.alignItems = "center";
  iconDiv.style.justifyContent = "center";
  iconDiv.style.position = "fixed";
  iconDiv.style.zIndex = "100";
  iconDiv.style.opacity = "0";
  iconDiv.style.cursor = "pointer";
  iconDiv.style.transition = "background 0.2s ease, opacity 0.2s ease";

  iconDiv.addEventListener("click", () => {
    showPanel();
  });

  const img = document.createElement("img");
  img.className = "pg-icon-logo";
  img.src = chrome.runtime.getURL("assets/images/logo_mini.svg");
  img.style.width = "60%";
  img.style.height = "60%";
  img.style.filter = "invert(1)";
  img.style.position = "absolute";
  img.style.transition = "opacity 0.2s ease";
  img.style.pointerEvents = "none";
  iconDiv.appendChild(img);

  const numberSpan = document.createElement("span");
  numberSpan.className = "pg-icon-number";
  numberSpan.style.position = "absolute";
  numberSpan.style.opacity = "0";
  numberSpan.style.color = "white";
  numberSpan.style.fontSize = "12px";
  numberSpan.style.fontWeight = "600";
  numberSpan.style.transition = "opacity 0.2s ease";
  numberSpan.style.pointerEvents = "none";
  iconDiv.appendChild(numberSpan);

  document.body.appendChild(iconDiv);
  selectionIcon = iconDiv;

  requestAnimationFrame(() => {
    iconDiv.style.opacity = "1";
  });

  return iconDiv;
}

function updateIcon(iconDiv: HTMLElement, range: Range, count: number) {
  const rect = range.getBoundingClientRect();
  iconDiv.style.top = rect.bottom + "px";
  iconDiv.style.left = rect.right + "px";

  const img = iconDiv.querySelector<HTMLElement>(".pg-icon-logo");
  const numberSpan = iconDiv.querySelector<HTMLElement>(".pg-icon-number");
  if (!img || !numberSpan) return;

  if (count > 0) {
    img.style.opacity = "0";
    numberSpan.style.opacity = "1";
    numberSpan.textContent = String(count);
    iconDiv.style.background = "#dc2626";
  } else {
    img.style.opacity = "1";
    numberSpan.style.opacity = "0";
    iconDiv.style.background = "#7c3aed";
  }
}

function showIcon(range: Range, count: number) {
  const iconDiv = selectionIcon?.isConnected ? selectionIcon : createIcon();
  updateIcon(iconDiv, range, count);
}

function hideIcon() {
  const existing = selectionIcon;
  if (!existing) return;
  selectionIcon = null;
  existing.style.opacity = "0";
  setTimeout(() => existing.remove(), 200);
}

function createPanel(
  count: number,
  level: "limited" | "standard" | "full" | "guardian",
): HTMLElement {
  const panel = document.createElement("div");
  registerOwnUiRoot(panel);
  panel.id = "pg-panel";
  panel.style.position = "fixed";
  panel.style.zIndex = "101";
  panel.style.width = "300px";
  panel.style.background = "white";
  panel.style.color = "#18181b";
  panel.style.padding = "20px";
  panel.style.borderRadius = "18px";
  panel.style.boxShadow = "0 12px 32px rgba(0,0,0,0.16)";
  panel.style.fontFamily = "Poppins, sans-serif";
  panel.style.fontSize = "14px";
  panel.style.opacity = "0";
  panel.style.transition = "opacity 0.2s ease";
  panel.style.boxSizing = "border-box";

  // --- Sekcja 1: nagłówek z logo ---
  const header = document.createElement("div");
  header.style.display = "flex";
  header.style.alignItems = "center";
  header.style.gap = "10px";
  header.style.marginBottom = "18px";

  const logo = document.createElement("img");
  logo.src = chrome.runtime.getURL("assets/images/logo.svg");
  logo.style.width = "28px";
  logo.style.height = "28px";
  header.appendChild(logo);

  const title = document.createElement("span");
  title.textContent = "Phishing Guard";
  title.style.fontWeight = "600";
  title.style.fontSize = "20px";
  header.appendChild(title);

  panel.appendChild(header);

  // --- Sekcja 2: licznik "Catched phrases: N" ---
  const counterRow = document.createElement("div");
  counterRow.style.display = "flex";
  counterRow.style.alignItems = "center";
  counterRow.style.justifyContent = "space-between";
  counterRow.style.marginBottom = "16px";

  const counterLabel = document.createElement("span");
  counterLabel.textContent = "Catched phrases:";
  counterLabel.style.fontWeight = "400";
  counterRow.appendChild(counterLabel);

  const counterValue = document.createElement("span");
  counterValue.textContent = String(count);
  counterValue.style.fontWeight = "600";
  counterRow.appendChild(counterValue);

  panel.appendChild(counterRow);

  const separator = document.createElement("hr");
  separator.style.border = "none";
  separator.style.borderTop = "1px solid #e4e4e7";
  separator.style.margin = "0 0 16px 0";
  panel.appendChild(separator);

  const isLimited = level === "limited";

  // --- Sekcja 3: ostrzeżenie (stan Limited) ---

  if (isLimited) {
    const warning = document.createElement("div");
    warning.style.display = "flex";
    warning.style.alignItems = "flex-start";
    warning.style.gap = "10px";
    warning.style.marginBottom = "16px";

    const warningIcon = document.createElement("img");
    warningIcon.src = chrome.runtime.getURL("assets/images/warning.svg");
    warningIcon.style.width = "20px";
    warningIcon.style.height = "20px";
    warningIcon.style.flexShrink = "0";
    warningIcon.style.marginTop = "2px";
    warning.appendChild(warningIcon);

    const warningText = document.createElement("div");
    warningText.style.color = "#52525b";
    warningText.style.fontSize = "13px";
    warningText.style.lineHeight = "1.4";
    warningText.innerHTML =
      "To enable <strong>AI Analyze</strong>, change settings.";
    warning.appendChild(warningText);

    panel.appendChild(warning);
  }

  // --- Sekcja 4: przycisk (wyszarzony, stan Limited) ---
  const button = document.createElement("button");
  button.textContent = "Analize";
  button.style.width = "100%";
  button.style.padding = "12px";
  button.style.borderRadius = "999px";
  button.style.fontSize = "16px";
  button.style.fontWeight = "500";
  button.style.fontFamily = "Poppins, sans-serif";
  button.style.border = "none";

  if (isLimited) {
    button.style.background = "#e4e4e7";
    button.style.color = "#a1a1aa";
    button.style.cursor = "not-allowed";
    button.disabled = true;
  } else {
    button.style.background = "#7c3aed";
    button.style.color = "white";
    button.style.cursor = "pointer";
    button.addEventListener("click", async () => {
      if (level === "full" && !lastAnalysisRoot) return;
      if (level !== "full" && (!lastContainer || !lastRange)) return;

      const originalText = button.textContent;
      button.textContent = "";
      const spinner = createSpinner();
      button.appendChild(spinner);
      button.disabled = true;
      button.style.cursor = "not-allowed";
      button.style.opacity = "0.6";

      try {
        const result =
          level === "full" ?
            await analyzeElement(lastAnalysisRoot!)
          : await analyzeSelection(
              lastContainer!,
              lastRange!,
              lastSelectedText,
              lastPhrases,
            );
        const resultBox = panel.querySelector<HTMLElement>(".pg-result");
        if (resultBox) renderResult(resultBox, result);
      } catch (error) {
        console.error("Błąd analizy:", error);
      } finally {
        spinner.remove();
        button.textContent = originalText;
        button.disabled = false;
        button.style.cursor = "pointer";
        button.style.opacity = "1";
      }
    });
  }

  panel.appendChild(button);

  const resultBox = document.createElement("div");
  resultBox.className = "pg-result";
  resultBox.style.marginTop = "16px";
  resultBox.style.display = "none";
  panel.appendChild(resultBox);

  document.body.appendChild(panel);
  return panel;
}

async function showPanel(anchor?: HTMLElement) {
  hidePanel();

  const ref = anchor ?? selectionIcon;
  if (!ref) return;

  const stored = await chrome.storage.local.get("autonomyLevel");
  const level = (stored.autonomyLevel ?? "limited") as
    | "limited"
    | "standard"
    | "full"
    | "guardian";

  const panel = createPanel(lastCount, level);
  selectionPanel = panel;
  const rect = ref.getBoundingClientRect();
  const panelWidth = 300;
  const margin = 8;

  let left = rect.left;
  if (left + panelWidth > window.innerWidth - margin) {
    left = rect.right - panelWidth;
  }

  panel.style.top = rect.bottom + 8 + "px";
  panel.style.left = left + "px";

  requestAnimationFrame(() => {
    panel.style.opacity = "1";
  });
}

function hidePanel() {
  selectionPanel?.remove();
  selectionPanel = null;
}

function highlightSelection(range: Range) {
  removeHighlights();
  let container = range.commonAncestorContainer;
  if (container.nodeType === Node.TEXT_NODE) {
    container = container.parentElement!;
  }
  scanElement(container as Element);
  scanSuspiciousLinks(container as Element);
}

export function initSelectionListener() {
  injectPoppinsFont();
  injectMarkStyle();

  document.addEventListener("mouseup", (event) => {
    const target = event.target;
    if (target instanceof Node && isInsideOwnUi(target)) {
      return;
    }
    if (
      target instanceof Element &&
      target.closest("mark[data-phishing-mark]")
    ) {
      return;
    }

    const selection = window.getSelection();
    if (!selection) return;
    const selectedText = selection.toString();

    if (selectedText.trim().length > 0) {
      const range = selection.getRangeAt(0);
      lastRange = range;

      let container: Node = range.commonAncestorContainer;
      if (container.nodeType === Node.TEXT_NODE) {
        container = container.parentElement!;
      }
      lastContainer = container as Element;
      lastAnalysisRoot = findAnalysisRoot(lastContainer);

      const text = getRangeTextExcludingOwnUi(lastContainer, range);
      lastSelectedText = text;
      const found = suspiciousWords.filter((word) =>
        text.toLowerCase().includes(word.toLowerCase()),
      );
      lastCount = found.length;
      lastPhrases = found;

      showIcon(range, found.length);
      highlightSelection(range);
    } else {
      hideIcon();
      hidePanel();
      removeHighlights();
    }
  });

  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (isInsideOwnUi(target)) return;
    const mark = target.closest("mark[data-phishing-mark]");
    if (!mark) return;

    const container = mark.parentElement;
    if (!container) return;
    lastContainer = container;
    lastAnalysisRoot = findAnalysisRoot(mark);
    lastSelectedText = getTextContentExcludingOwnUi(container);
    lastPhrases = suspiciousWords.filter((w) =>
      lastSelectedText.toLowerCase().includes(w.toLowerCase()),
    );
    lastCount = lastPhrases.length;
    const range = document.createRange();
    range.selectNodeContents(container);
    lastRange = range;
    showPanel(mark as HTMLElement);
  });
}
