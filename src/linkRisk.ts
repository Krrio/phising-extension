import { extractHostname, getEffectiveHref, hasLinkMismatch } from "./links";
import { isSuspiciousDomain } from "./suspiciousDomain";

export interface LinkRisk {
  effectiveHref: string;
  hostname: string | null;
  mismatch: boolean;
  suspiciousDomain: boolean;
  risky: boolean;
}

/** Keeps decoration, click interception and Guardian signals in sync. */
export function getLinkRisk(linkText: string, href: string): LinkRisk {
  const effectiveHref = getEffectiveHref(href);
  const hostname = extractHostname(effectiveHref);
  const mismatch = hasLinkMismatch(linkText, effectiveHref);
  const suspiciousDomain = Boolean(
    hostname && isSuspiciousDomain(hostname),
  );

  return {
    effectiveHref,
    hostname,
    mismatch,
    suspiciousDomain,
    risky: mismatch || suspiciousDomain,
  };
}
