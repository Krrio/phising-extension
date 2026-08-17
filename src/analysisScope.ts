import {
  isEditableOrControl,
  isElementSelfHidden,
  isElementVisible,
  isInsideEditableOrControl,
} from "./domVisibility";
import { getVisibleTextContentExcludingOwnUi } from "./ownUi";

export type MailProvider = "gmail" | "outlook" | "generic";
export type ScopeConfidence = "strong" | "medium" | "fallback";

export interface AnalysisScope {
  provider: MailProvider;
  /** Stable wrapper used to identify the message across scans. */
  container: Element;
  /** Narrow subtree whose visible text and links are sent for analysis. */
  contentRoot: Element;
  /** Smallest wrapper that can safely be replaced by a Guardian shield. */
  hideTarget: Element;
  messageKey: string;
  confidence: ScopeConfidence;
  /** Whether visible, non-editor content may be scanned and sent for analysis. */
  canAnalyze: boolean;
  /** Whether the complete hideTarget is safe to replace with a shield. */
  canAutoHide: boolean;
}

export interface AnalysisScopeOptions {
  hostname?: string;
  maxTextLength?: number;
}

const DEFAULT_MAX_TEXT_LENGTH = 8_000;
const MIN_FALLBACK_TEXT_LENGTH = 40;
const elementKeys = new WeakMap<Element, number>();
let nextElementKey = 1;

function normalizeHostname(hostname: string): string {
  return hostname.trim().toLowerCase().replace(/\.$/, "");
}

function currentHostname(start?: Element, override?: string): string {
  if (override !== undefined) return normalizeHostname(override);

  const fromDocument = start?.ownerDocument?.location?.hostname;
  if (fromDocument) return normalizeHostname(fromDocument);

  if (typeof location !== "undefined") {
    return normalizeHostname(location.hostname);
  }

  return "";
}

export function detectMailProvider(hostname: string): MailProvider {
  const normalized = normalizeHostname(hostname);

  if (normalized === "mail.google.com") return "gmail";

  if (
    normalized === "outlook.live.com" ||
    normalized === "outlook.office.com" ||
    normalized === "outlook.office365.com" ||
    normalized === "outlook.cloud.microsoft" ||
    normalized.endsWith(".outlook.com")
  ) {
    return "outlook";
  }

  return "generic";
}

function bodyFor(start: Element): Element | null {
  return (
    start.ownerDocument?.body ??
    (typeof document !== "undefined" ? document.body : null)
  );
}

function elementTextLength(element: Element): number {
  // Lightweight fake DOMs used by unit tests need not implement childNodes.
  const childNodes = (element as Element & { childNodes?: NodeListOf<ChildNode> })
    .childNodes;
  if (!childNodes) return element.textContent?.trim().length ?? 0;
  return getVisibleTextContentExcludingOwnUi(element).length;
}

function isWithinLimit(element: Element, maxTextLength: number): boolean {
  return elementTextLength(element) <= maxTextLength;
}

function closestMatching(
  start: Element,
  selector: string,
  boundary: Element | null,
): Element | null {
  let current: Element | null = start;

  while (current && current !== boundary) {
    if (current.matches(selector)) return current;
    current = current.parentElement;
  }

  return null;
}

function closestNonEditable(
  start: Element,
  selector: string,
  boundary: Element | null,
): Element | null {
  let current: Element | null = start;

  while (current && current !== boundary) {
    if (
      current.matches(selector) &&
      !isInsideEditableOrControl(start, current)
    ) {
      return current;
    }
    current = current.parentElement;
  }

  return null;
}

function messageDocumentRoot(
  start: Element,
  container: Element,
): Element | null {
  const closest = closestNonEditable(
    start,
    "[role='document']",
    container.parentElement,
  );
  if (
    closest &&
    container.contains(closest) &&
    isVisibleInsideRoot(closest, container)
  ) {
    return closest;
  }

  for (const candidate of Array.from(
    container.querySelectorAll("[role='document']"),
  )) {
    const owningMessage = candidate.closest(
      "[data-message-id],[data-legacy-message-id]",
    );
    if (owningMessage && owningMessage !== container) continue;

    if (
      !isInsideEditableOrControl(candidate, container) &&
      isVisibleInsideRoot(candidate, container)
    ) {
      return candidate;
    }
  }

  return null;
}

function isReadOnlyContent(root: Element): boolean {
  if (isInsideEditableOrControl(root)) return false;

  const possibleEditors = root.querySelectorAll(
    "input,textarea,select,[role='textbox'],[contenteditable]",
  );
  return !Array.from(possibleEditors).some(
    (element) =>
      isEditableOrControl(element) && isVisibleInsideRoot(element, root),
  );
}

function isVisibleInsideRoot(element: Element, root: Element): boolean {
  let current: Element | null = element;

  // Deliberately do not inspect `root` itself. Guardian may currently hide the
  // wrapper with its own stylesheet; a newly inserted, otherwise visible
  // reply editor must still revoke permission to hide that wrapper.
  while (current && current !== root) {
    if (isElementSelfHidden(current)) return false;
    current = current.parentElement;
  }

  return current === root;
}

function isExcludedGmailChrome(
  container: Element,
  includeDescendantCheckbox = true,
): boolean {
  return Boolean(
    container.closest(
      "aside,[role='complementary'],nav,[role='navigation'],[role='grid'],[role='listbox'],[role='menu'],[role='tree'],dialog,[role='dialog']",
    ) ||
      (includeDescendantCheckbox &&
        container.querySelector("[role='checkbox']")),
  );
}

function fallbackRoot(
  start: Element,
  maxTextLength: number,
  boundary: Element | null,
): Element {
  let current = start.parentElement;
  let nearestUsable: Element | null = null;

  while (current && current !== boundary) {
    if (isInsideEditableOrControl(start, current)) {
      current = current.parentElement;
      continue;
    }

    const textLength = elementTextLength(current);
    if (textLength > maxTextLength) break;

    nearestUsable ??= current;
    if (textLength >= MIN_FALLBACK_TEXT_LENGTH) return current;
    current = current.parentElement;
  }

  const parent = start.parentElement;
  return nearestUsable ?? (parent && parent !== boundary ? parent : start);
}

function keyForElement(provider: MailProvider, element: Element): string {
  let key = elementKeys.get(element);
  if (key === undefined) {
    key = nextElementKey;
    nextElementKey += 1;
    elementKeys.set(element, key);
  }
  return `${provider}:element-${key}`;
}

function gmailScope(
  start: Element,
  body: Element | null,
): AnalysisScope | null {
  // Both attributes describe the same semantic tier. The nearest message
  // wins; attribute preference matters only if that same element has both.
  const container = closestMatching(
    start,
    "[data-message-id],[data-legacy-message-id]",
    body,
  );

  if (container) {
    const contentRoot = messageDocumentRoot(start, container) ?? container;
    // Gmail's legacy id is the canonical RFC-style message identity and tends
    // to survive SPA rerenders, while the modern wrapper id may be added or
    // replaced during hydration.
    const legacyIdentifier = container
      .getAttribute("data-legacy-message-id")
      ?.trim();
    const modernIdentifier = container.getAttribute("data-message-id")?.trim();
    const identifier = legacyIdentifier || modernIdentifier;

    return {
      provider: "gmail",
      container,
      contentRoot,
      hideTarget: container,
      messageKey:
        identifier ? `gmail:${identifier}` : keyForElement("gmail", container),
      confidence: "strong",
      // A stable message id is sufficient for analysis. Editable descendants
      // are removed by the visible-content extractor, but still revoke the
      // separate permission to hide the complete wrapper.
      canAnalyze: !isExcludedGmailChrome(container, false),
      // The body may be read-only while Gmail keeps a live reply editor next
      // to it in the same message wrapper. Analysing the body is safe, but
      // hiding that wrapper would also hide the user's draft.
      canAutoHide:
        !isExcludedGmailChrome(container, false) &&
        isReadOnlyContent(contentRoot) &&
        isReadOnlyContent(container),
    };
  }

  const listItem = closestMatching(start, "[role='listitem']", body);
  if (!listItem) return null;

  const contentRoot = messageDocumentRoot(start, listItem) ?? listItem;
  const inboxLike = isExcludedGmailChrome(listItem);
  const inMainContent = Boolean(listItem.closest("main,[role='main']"));
  const hasDocumentBody = contentRoot !== listItem;
  const isMessageLike = !inboxLike && (inMainContent || hasDocumentBody);

  return {
    provider: "gmail",
    container: listItem,
    contentRoot,
    hideTarget: listItem,
    messageKey: keyForElement("gmail", listItem),
    confidence: "medium",
    canAnalyze: isMessageLike,
    canAutoHide:
      isMessageLike &&
      isReadOnlyContent(contentRoot) &&
      isReadOnlyContent(listItem),
  };
}

function outlookScope(
  start: Element,
  body: Element | null,
): AnalysisScope | null {
  const documentRoot = closestNonEditable(
    start,
    "[role='document']",
    body,
  );
  if (!documentRoot) return null;

  return {
    provider: "outlook",
    container: documentRoot,
    contentRoot: documentRoot,
    hideTarget: documentRoot,
    messageKey: keyForElement("outlook", documentRoot),
    confidence: "strong",
    canAnalyze: isReadOnlyContent(documentRoot),
    canAutoHide: isReadOnlyContent(documentRoot),
  };
}

function genericSemanticScope(
  start: Element,
  body: Element | null,
  maxTextLength: number,
): AnalysisScope | null {
  const explicit = closestMatching(
    start,
    "[data-phishing-analysis-root]",
    body,
  );
  if (explicit) {
    return {
      provider: "generic",
      container: explicit,
      contentRoot: explicit,
      hideTarget: explicit,
      messageKey: keyForElement("generic", explicit),
      confidence: "strong",
      canAnalyze: true,
      canAutoHide: isReadOnlyContent(explicit),
    };
  }

  const semantic = closestNonEditable(
    start,
    "article,[role='article'],[role='document']",
    body,
  );
  if (!semantic || !isWithinLimit(semantic, maxTextLength)) return null;

  return {
    provider: "generic",
    container: semantic,
    contentRoot: semantic,
    hideTarget: semantic,
    messageKey: keyForElement("generic", semantic),
    confidence: "medium",
    canAnalyze: true,
    canAutoHide: false,
  };
}

export function resolveAnalysisScope(
  start: Element,
  options: AnalysisScopeOptions = {},
): AnalysisScope {
  const hostname = currentHostname(start, options.hostname);
  const provider = detectMailProvider(hostname);
  const body = bodyFor(start);
  const maxTextLength = options.maxTextLength ?? DEFAULT_MAX_TEXT_LENGTH;

  // Explicit roots are an opt-in contract for generic integrations and power
  // the local playground. Do not let message HTML override a known provider's
  // adapter by spoofing the opt-in attribute.
  const explicit =
    provider === "generic" ?
      genericSemanticScope(start, body, maxTextLength)
    : null;
  if (explicit?.confidence === "strong") return explicit;

  const providerScope =
    provider === "gmail" ? gmailScope(start, body)
    : provider === "outlook" ? outlookScope(start, body)
    : null;
  if (providerScope) return providerScope;

  if (explicit) return explicit;

  const fallback = fallbackRoot(start, maxTextLength, body);
  return {
    provider,
    container: fallback,
    contentRoot: fallback,
    hideTarget: fallback,
    messageKey: keyForElement(provider, fallback),
    confidence: "fallback",
    canAnalyze: false,
    canAutoHide: false,
  };
}

export function findAnalysisRoot(
  start: Element,
  options: AnalysisScopeOptions = {},
): Element {
  return resolveAnalysisScope(start, options).container;
}

function queryElements(root: ParentNode, selector: string): Element[] {
  const matches = Array.from(root.querySelectorAll(selector));
  if (root instanceof Element && root.matches(selector)) matches.unshift(root);
  return matches;
}

/** Returns visible message scopes known to the active adapter. */
export function collectAnalysisScopes(
  root: ParentNode,
  options: AnalysisScopeOptions = {},
): AnalysisScope[] {
  const sample = root instanceof Element ? root : undefined;
  const hostname = currentHostname(sample, options.hostname);
  const provider = detectMailProvider(hostname);
  let seeds: Element[];

  if (provider === "gmail") {
    seeds = queryElements(
      root,
      "[data-message-id],[data-legacy-message-id]",
    );

    seeds.push(...queryElements(root, "[role='listitem']"));

    for (const documentRoot of queryElements(root, "[role='document']")) {
      const listItem = documentRoot.closest("[role='listitem']");
      if (listItem) seeds.push(documentRoot);
    }
  } else if (provider === "outlook") {
    seeds = queryElements(root, "[role='document']");
  } else {
    seeds = queryElements(
      root,
      "[data-phishing-analysis-root],article,[role='article'],[role='document']",
    );
  }

  const byContainer = new Map<Element, AnalysisScope>();
  const visibilityCache = new WeakMap<Element, boolean>();

  for (const seed of seeds) {
    if (!isElementVisible(seed, null, visibilityCache)) continue;
    if (isInsideEditableOrControl(seed)) continue;

    const scope = resolveAnalysisScope(seed, { ...options, hostname });
    if (scope.confidence === "fallback") continue;
    if (!scope.canAnalyze) continue;
    if (!isElementVisible(scope.contentRoot, null, visibilityCache)) continue;
    if (!byContainer.has(scope.container)) {
      byContainer.set(scope.container, scope);
    }
  }

  const scopes = Array.from(byContainer.values());
  return scopes.filter(
    (scope) =>
      !scopes.some(
        (other) =>
          other !== scope &&
          scope.container.contains(other.container) &&
          scope.confidence !== "strong",
      ),
  );
}
