const NON_CONTENT_TAGS = new Set([
  "SCRIPT",
  "STYLE",
  "TEMPLATE",
  "NOSCRIPT",
  "INPUT",
  "TEXTAREA",
  "SELECT",
  "OPTION",
]);

function normalizedAttribute(element: Element, name: string): string | null {
  const getAttribute = (element as Element & {
    getAttribute?: (attributeName: string) => string | null;
  }).getAttribute;
  if (typeof getAttribute !== "function") return null;
  const value = getAttribute.call(element, name);
  return value === null ? null : value.trim().toLowerCase();
}

export function isEditableOrControl(element: Element): boolean {
  const tagName = (element.tagName ?? "").toUpperCase();
  if (NON_CONTENT_TAGS.has(tagName)) return true;

  const role = normalizedAttribute(element, "role");
  if (role === "textbox") return true;

  const contentEditable = normalizedAttribute(element, "contenteditable");
  return contentEditable !== null && contentEditable !== "false";
}

export function isInsideEditableOrControl(
  element: Element,
  boundary: Element | null = null,
): boolean {
  let current: Element | null = element;

  while (current) {
    if (isEditableOrControl(current)) return true;
    if (current === boundary) break;
    current = current.parentElement;
  }

  return false;
}

function computedStyleFor(element: Element): CSSStyleDeclaration | null {
  const view = element.ownerDocument?.defaultView;

  try {
    if (view?.getComputedStyle) return view.getComputedStyle(element);
    if (typeof getComputedStyle === "function") return getComputedStyle(element);
  } catch {
    // Detached or synthetic nodes may not expose computed styles.
  }

  return null;
}

export function isElementSelfHidden(element: Element): boolean {
  const hasAttribute = (element as Element & {
    hasAttribute?: (attributeName: string) => boolean;
  }).hasAttribute;
  if (
    typeof hasAttribute === "function" &&
    (hasAttribute.call(element, "hidden") || hasAttribute.call(element, "inert"))
  ) {
    return true;
  }

  if (normalizedAttribute(element, "aria-hidden") === "true") return true;
  if (
    (element.tagName ?? "").toUpperCase() === "INPUT" &&
    normalizedAttribute(element, "type") === "hidden"
  ) {
    return true;
  }

  const style = computedStyleFor(element);
  if (!style) return false;

  return (
    style.display === "none" ||
    style.visibility === "hidden" ||
    style.visibility === "collapse" ||
    style.contentVisibility === "hidden"
  );
}

export function isElementVisible(
  element: Element,
  boundary: Element | null = null,
  cache?: WeakMap<Element, boolean>,
): boolean {
  const cached = cache?.get(element);
  if (cached !== undefined) return cached;

  const chain: Element[] = [];
  let current: Element | null = element;
  let visible = true;

  while (current) {
    const ancestorCached = cache?.get(current);
    if (ancestorCached !== undefined) {
      visible = ancestorCached;
      break;
    }

    chain.push(current);
    if (isElementSelfHidden(current)) {
      visible = false;
      break;
    }
    if (current === boundary) break;
    current = current.parentElement;
  }

  for (const item of chain) cache?.set(item, visible);
  return visible;
}

export function shouldSkipContentSubtree(element: Element): boolean {
  return (
    NON_CONTENT_TAGS.has((element.tagName ?? "").toUpperCase()) ||
    isEditableOrControl(element)
  );
}
