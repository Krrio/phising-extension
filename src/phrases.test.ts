import { describe, expect, test } from "vitest";
import { findNearestPhrase } from "./phrases";

describe("find phrases", () => {
  test("Find phrase and return the first one", () => {
    const result = findNearestPhrase("password expired", 0);
    expect(result).toEqual({ phrase: "password expired", position: 0 });
  });

  test("Returns earliest phrase in text, not first in list", () => {
    const result = findNearestPhrase(
      "urgent action then verify your account",
      0,
    );
    expect(result).toEqual({ phrase: "urgent action", position: 0 });
  });

  test("Returns null and -1 for safe text", () => {
    const result = findNearestPhrase("hello world nothing here", 0);
    expect(result).toEqual({ phrase: null, position: -1 });
  });

  test("Respect starting position", () => {
    const result = findNearestPhrase(
      "urgent action then verify your account",
      15,
    );
    expect(result).toEqual({ phrase: "verify your account", position: 19 });
  });

  test("Phishing text between safe words", () => {
    const result = findNearestPhrase("hello verify your account please", 0);
    expect(result).toEqual({ phrase: "verify your account", position: 6 });
  });

  test("Phishing text hidden among safe words", () => {
    const result = findNearestPhrase("helloverifyyouraccountplease", 0);
    expect(result).toEqual({ phrase: null, position: -1 });
  });
});
