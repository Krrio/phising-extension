import { describe, expect, test } from "vitest";
import { levenshtein } from "./levensthein";

describe("levenshtein", () => {
  test("identical strings have distance 0", () => {
    expect(levenshtein("paypal", "paypal")).toBe(0);
  });

  test("single substitution has distance 1", () => {
    expect(levenshtein("paypal", "paypa1")).toBe(1);
  });

  test("empty string equals length of other", () => {
    expect(levenshtein("", "abc")).toBe(3);
  });
});
