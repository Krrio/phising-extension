import { describe, expect, test } from "vitest";
import { extractHostname, hasLinkMismatch } from "./links";

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
});
