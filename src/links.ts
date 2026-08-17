import { getDomain } from "tldts";

function parseHttpUrl(text: string): URL | null {
  const looksLikeDomain = text.includes(".") && !text.includes(" ");

  try {
    const parsed = new URL(text);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed;
    }
    return null;
  } catch {
    if (!looksLikeDomain) return null;

    try {
      return new URL(`https://${text}`);
    } catch {
      return null;
    }
  }
}

function redirectTarget(parsed: URL): string | null {
  const hostname = parsed.hostname.toLowerCase();
  const isOutlookSafeLink =
    hostname === "safelinks.protection.outlook.com" ||
    hostname.endsWith(".safelinks.protection.outlook.com");
  if (isOutlookSafeLink) return parsed.searchParams.get("url");

  const isGoogleRedirect =
    (hostname === "google.com" || hostname === "www.google.com") &&
    parsed.pathname === "/url";
  if (isGoogleRedirect) {
    return parsed.searchParams.get("q") ?? parsed.searchParams.get("url");
  }

  return null;
}

/** Unwraps only redirect formats whose owner and target parameter are known. */
export function getEffectiveHref(href: string): string {
  let current = href;

  for (let depth = 0; depth < 3; depth += 1) {
    const parsed = parseHttpUrl(current);
    if (!parsed) return current;

    const target = redirectTarget(parsed);
    if (!target) return parsed.href;

    const parsedTarget = parseHttpUrl(target);
    if (!parsedTarget) return parsed.href;
    current = parsedTarget.href;
  }

  return current;
}

export function extractHostname(text: unknown): string | null {
  if (typeof text !== "string") return null;
  return parseHttpUrl(getEffectiveHref(text))?.hostname ?? null;
}

export function hasLinkMismatch(linkText: string, href: string) {
  const hrefHost = extractHostname(href);
  const textHost = extractHostname(linkText);

  if (textHost === null) {
    return false;
  } else if (hrefHost === null) {
    return false;
  } else if (
    (getDomain(textHost) ?? textHost) !== (getDomain(hrefHost) ?? hrefHost)
  ) {
    return true;
  }
  return false;
}
