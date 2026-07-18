import { describe, expect, test } from "vitest";
import { isSuspiciousDomain } from "./suspiciousDomain";

describe("isSuspiciousDomain", () => {
  test("detects typosquat with digit substitution", () => {
    expect(isSuspiciousDomain("paypa1.com")).toBe(true);
  });

  test("detects zero-for-o substitution", () => {
    expect(isSuspiciousDomain("g00gle.com")).toBe(true);
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
});
