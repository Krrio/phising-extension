import { describe, expect, test } from "vitest";
import { extractHostname, getEffectiveHref, hasLinkMismatch } from "./links";
import { isSuspiciousDomain } from "./suspiciousDomain";

describe("extractHostname", () => {
  test("extracts hostname from full URL", () => {
    const result = extractHostname("https://paypal.com/login");
    expect(result).toEqual("paypal.com");
  });

  test("returns null for non-URL text", () => {
    const result = extractHostname("Kliknij tutaj");
    expect(result).toEqual(null);
  });

  test("extracts hostname from domain without protocol", () => {
    const result = extractHostname("paypal.com");
    expect(result).toBe("paypal.com");
  });

  test("returns null for plain word without dot", () => {
    const result = extractHostname("Zaloguj");
    expect(result).toBe(null);
  });

  test("safely rejects a non-string SVG-style href value", () => {
    expect(extractHostname({ baseVal: "https://example.com" })).toBe(null);
  });
});

describe("hasLinkMismatch", () => {
  test("treats www and the bare registrable domain as the same target", () => {
    expect(
      hasLinkMismatch("paypal.com", "https://www.paypal.com/login"),
    ).toBe(false);
  });

  test("detects a different registrable target", () => {
    expect(
      hasLinkMismatch("paypal.com", "https://paypa1.example/login"),
    ).toBe(true);
  });

  test("keeps a mismatch to reserved .invalid risky even when the domain itself is ignored", () => {
    const href = "https://attacker.invalid/paypal-login";
    const hostname = extractHostname(href);

    expect(hostname).toBe("attacker.invalid");
    expect(isSuspiciousDomain(hostname!)).toBe(false);
    expect(hasLinkMismatch("paypal.com", href)).toBe(true);
  });

  test("compares against the destination inside Outlook Safe Links", () => {
    const safeLink =
      "https://nam01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fwww.paypal.com%2Flogin&data=tracking";

    expect(getEffectiveHref(safeLink)).toBe("https://www.paypal.com/login");
    expect(hasLinkMismatch("paypal.com", safeLink)).toBe(false);
  });

  test("unwraps Google's explicit mail redirect but not unknown redirectors", () => {
    expect(
      getEffectiveHref(
        "https://www.google.com/url?q=https%3A%2F%2Fexample.com%2Faccount",
      ),
    ).toBe("https://example.com/account");
    expect(
      extractHostname(
        "https://redirect.example/?url=https%3A%2F%2Fpaypal.com",
      ),
    ).toBe("redirect.example");
  });
});
