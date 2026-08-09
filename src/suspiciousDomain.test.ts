import { describe, expect, test } from "vitest";
import { analyzeDomain, isSuspiciousDomain } from "./suspiciousDomain";

describe("isSuspiciousDomain", () => {
  test("detects typosquat with digit substitution", () => {
    expect(isSuspiciousDomain("paypa1.com")).toBe(true);
  });

  test("detects zero-for-o substitution", () => {
    expect(isSuspiciousDomain("g00gle.com")).toBe(true);
  });

  test("keeps character-substitution provenance", () => {
    const analysis = analyzeDomain("paypa1.com");

    expect(analysis).toMatchObject({
      isSuspicious: true,
      matchedBrand: "paypal",
      provenance: "leet",
    });
    expect(analysis.reasons).toContain("character-substitution");
  });

  test.each([
    "paypal123.com",
    "123paypal.com",
    "office365123.de",
    "przelewy24123.com",
  ])(
    "detects a numeric affix beside a brand: %s",
    (domain) => {
      const analysis = analyzeDomain(domain);

      expect(analysis.isSuspicious).toBe(true);
      expect(analysis.reasons).toContain("numeric-affix");
    },
  );

  test("prefers the longest matching brand for a numeric affix", () => {
    expect(analyzeDomain("office365123.de").matchedBrand).toBe("office365");
  });

  test("detects an unrecognized separator inside a brand", () => {
    const analysis = analyzeDomain("pay-pal.com");

    expect(analysis.isSuspicious).toBe(true);
    expect(analysis.reasons).toContain("brand-label-obfuscation");
  });

  test.each(["t-mobile.de", "x-kom.de", "credit-agricole.de"])(
    "allows an official separator form on a regional suffix: %s",
    (domain) => {
      expect(isSuspiciousDomain(domain)).toBe(false);
    },
  );

  test("keeps fuzzy-match provenance", () => {
    const analysis = analyzeDomain("paypol.com");

    expect(analysis).toMatchObject({
      isSuspicious: true,
      matchedBrand: "paypal",
      provenance: "fuzzy",
    });
    expect(analysis.reasons).toContain("lookalike-spelling");
  });

  test("real brand is NOT suspicious (distance 0)", () => {
    expect(isSuspiciousDomain("paypal.com")).toBe(false);
  });

  test("real brand google is NOT suspicious", () => {
    expect(isSuspiciousDomain("google.com")).toBe(false);
  });

  test("unrelated domain is NOT suspicious", () => {
    expect(isSuspiciousDomain("example.com")).toBe(false);
  });

  test.each(["localhost", "127.0.0.1", "appleid.invalid"])(
    "ignores non-public hostnames: %s",
    (domain) => {
      expect(isSuspiciousDomain(domain)).toBe(false);
    },
  );

  test.each([
    "google.de",
    "google.fr",
    "google.co.uk",
    "amazon.it",
    "huawei.de",
    "lenovo.fr",
    "visa.co.uk",
    "pzu.com",
  ])("allows a plain regional company domain: %s", (domain) => {
    expect(isSuspiciousDomain(domain)).toBe(false);
  });

  test.each(["support.google.de", "mail.google.de", "apple.google.de"])(
    "does not mistake a normal subdomain of a regional root for phishing: %s",
    (domain) => {
      expect(isSuspiciousDomain(domain)).toBe(false);
    },
  );

  test.each(["paypal-login.com", "allegro-pomoc.net"])(
    "detects a suspicious addition beside a brand: %s",
    (domain) => {
      const analysis = analyzeDomain(domain);

      expect(analysis.isSuspicious).toBe(true);
      expect(analysis.reasons).toContain("suspicious-addition");
      expect(analysis.provenance).toBe("addition-stripped");
    },
  );

  test("detects a suspicious addition on a compound public suffix", () => {
    expect(isSuspiciousDomain("paypal-login.co.uk")).toBe(true);
  });

  test("detects an exact brand in a foreign subdomain", () => {
    const analysis = analyzeDomain("paypal.secure-verify.com");

    expect(analysis.isSuspicious).toBe(true);
    expect(analysis.matchedBrand).toBe("paypal");
    expect(analysis.reasons).toContain("brand-in-foreign-subdomain");
  });

  test("detects a brand in a foreign subdomain on a compound public suffix", () => {
    expect(isSuspiciousDomain("google.evil.co.uk")).toBe(true);
  });

  test("still trusts subdomains inside an official registrable domain", () => {
    expect(isSuspiciousDomain("mail.google.com")).toBe(false);
  });

  test.each(["google.xyz", "pzu.top", "amazon.tk"])(
    "uses a risky suffix as supporting evidence: %s",
    (domain) => {
      const analysis = analyzeDomain(domain);

      expect(analysis.isSuspicious).toBe(true);
      expect(analysis.reasons).toContain("risky-public-suffix");
    },
  );

  test("uses a private hosting suffix as supporting evidence", () => {
    const analysis = analyzeDomain("paypal.github.io");

    expect(analysis.isSuspicious).toBe(true);
    expect(analysis.reasons).toContain("private-or-shared-hosting");
  });

  test("detects a brand tenant below a private AWS suffix", () => {
    const analysis = analyzeDomain("paypal.s3.amazonaws.com");

    expect(analysis.isSuspicious).toBe(true);
    expect(analysis.reasons).toContain("private-or-shared-hosting");
  });

  test("keeps lookalike detection on a compound public suffix", () => {
    expect(isSuspiciousDomain("g00gle.co.uk")).toBe(true);
  });

  test("does not extend the amazonaws allowlist entry to tenants", () => {
    const analysis = analyzeDomain("paypal.amazonaws.com");

    expect(analysis.isSuspicious).toBe(true);
    expect(analysis.reasons).toContain("brand-in-foreign-subdomain");
  });

  test("does not grant regional-domain policy to product aliases", () => {
    const analysis = analyzeDomain("appleid.de");

    expect(analysis.isSuspicious).toBe(true);
    expect(analysis.reasons).toContain("non-regional-brand-domain");
  });

  test("extracts the hostname through URL parsing", () => {
    expect(
      isSuspiciousDomain("https://paypal-login.com/account?next=home"),
    ).toBe(true);
  });

  test("canonicalizes an IDN hostname to ASCII", () => {
    const analysis = analyzeDomain("https://żółć.pl");

    expect(analysis.hostname).toBe("xn--kda4b0koi.pl");
    expect(analysis.isSuspicious).toBe(false);
  });
});
