import { describe, expect, test } from "vitest";
import { normalize } from "./normalize";

describe("normalize", () => {
  test("Normalize whitespaces and change them to normal space", () => {
    const result = normalize("a\n  b");
    expect(result).toEqual({ normalized: "a b", map: [0, 1, 4] });
  });

  test("Check empty string", () => {
    const result = normalize("");
    expect(result).toEqual({ normalized: "", map: [] });
  });

  test("Check only whitespaces", () => {
    const result = normalize("   ");
    expect(result).toEqual({ normalized: " ", map: [0] });
  });

  test("Check text without whitespaces", () => {
    const result = normalize("abc");
    expect(result).toEqual({ normalized: "abc", map: [0, 1, 2] });
  });

  test("Check if map jumps properly between chars", () => {
    const result = normalize("a  b");
    expect(result).toEqual({ normalized: "a b", map: [0, 1, 3] });
  });

  test("Check whitespaced after text", () => {
    const result = normalize("a b    ");
    expect(result).toEqual({ normalized: "a b ", map: [0, 1, 2, 3] });
  });
});
