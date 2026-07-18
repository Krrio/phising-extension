export function extractHostname(text: string): string | null {
  const looksLikeDomain = text.includes(".") && !text.includes(" ");
  try {
    return new URL(text).hostname;
  } catch {
    try {
      if (looksLikeDomain) return new URL("https://" + text).hostname;
    } catch {
      return null;
    }
    return null;
  }
}

export function hasLinkMismatch(linkText: string, href: string) {
  const hrefHost = extractHostname(href);
  const textHost = extractHostname(linkText);

  if (textHost === null) {
    return false;
  } else if (hrefHost === null) {
    return false;
  } else if (textHost != hrefHost) {
    return true;
  }
  return false;
}
