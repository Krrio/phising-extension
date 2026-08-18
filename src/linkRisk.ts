import { extractHostname, getEffectiveHref, hasLinkMismatch } from "./links";
import { analyzeDomain } from "./suspiciousDomain";

export interface LinkRisk {
  effectiveHref: string;
  hostname: string | null;
  mismatch: boolean;
  suspiciousDomain: boolean;
  official: boolean;
  risky: boolean;
}

/** Keeps decoration, click interception and Guardian signals in sync. */
export function getLinkRisk(linkText: string, href: string): LinkRisk {
  const effectiveHref = getEffectiveHref(href);
  const hostname = extractHostname(effectiveHref);
  const mismatch = hasLinkMismatch(linkText, effectiveHref);
  const analysis = hostname ? analyzeDomain(hostname) : null;
  const suspiciousDomain = analysis?.isSuspicious ?? false;
  const official = analysis?.isOfficial ?? false;

  return {
    effectiveHref,
    hostname,
    mismatch,
    suspiciousDomain,
    official,
    risky: mismatch || suspiciousDomain,
  };
}
