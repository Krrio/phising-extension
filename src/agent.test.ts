import { describe, expect, test } from "vitest";
import {
  createGuardianFingerprint,
  getGuardianVerdictAction,
  getHiddenBlockReconciliation,
  limitGuardianContent,
} from "./agent";
import type { AnalyzeResult } from "./messages";

function verdict(
  result: Pick<AnalyzeResult, "verdict" | "trustScore" | "confidence">,
): AnalyzeResult {
  return {
    ...result,
    reasoning: "test",
    categories: [],
  };
}

describe("Guardian content identity", () => {
  test("fingerprint changes with message identity, text and link targets", () => {
    const baseline = createGuardianFingerprint("gmail:one", "same text", [
      "https://safe.example/path",
    ]);

    expect(
      createGuardianFingerprint("gmail:two", "same text", [
        "https://safe.example/path",
      ]),
    ).not.toBe(baseline);
    expect(
      createGuardianFingerprint("gmail:one", "changed text", [
        "https://safe.example/path",
      ]),
    ).not.toBe(baseline);
    expect(
      createGuardianFingerprint("gmail:one", "same text", [
        "https://evil.example/path",
      ]),
    ).not.toBe(baseline);
  });

  test("normalizes link order without losing link changes", () => {
    expect(
      createGuardianFingerprint("message", "content", [
        "https://b.test",
        "https://a.test",
      ]),
    ).toBe(
      createGuardianFingerprint("message", "content", [
        "https://a.test",
        "https://b.test",
      ]),
    );
  });

  test("normalizes equivalent whitespace without hiding character changes", () => {
    const compact = createGuardianFingerprint(
      "gmail:message",
      "UWAGA! Kliknij",
      [],
    );
    const splitTextNodes = createGuardianFingerprint(
      "gmail:message",
      "UWAGA!\n   Kliknij",
      [],
    );
    const changedPunctuation = createGuardianFingerprint(
      "gmail:message",
      "UWAGA? Kliknij",
      [],
    );

    expect(splitTextNodes).toBe(compact);
    expect(changedPunctuation).not.toBe(compact);
  });

  test("keeps the mapping between visible link text and its target", () => {
    const original = createGuardianFingerprint("message", "A B", [
      { text: "A", href: "https://safe.test" },
      { text: "B", href: "https://evil.test" },
    ]);
    const swapped = createGuardianFingerprint("message", "A B", [
      { text: "A", href: "https://evil.test" },
      { text: "B", href: "https://safe.test" },
    ]);

    expect(swapped).not.toBe(original);
    expect(original.length).toBeLessThan(80);
  });

  test("invalidates the fingerprint for changes beyond payload link limits", () => {
    const prefix = `https://example.test/${"x".repeat(2_100)}`;
    const baseline = createGuardianFingerprint("message", "content", [
      { text: `${"a".repeat(250)} one`, href: `${prefix}/one` },
    ]);
    const changed = createGuardianFingerprint("message", "content", [
      { text: `${"a".repeat(250)} two`, href: `${prefix}/two` },
    ]);

    expect(changed).not.toBe(baseline);
  });
});

describe("Guardian content limit", () => {
  test("keeps both ends of a long message within the backend limit", () => {
    const content = `BEGIN-${"x".repeat(10_000)}-END`;
    const limited = limitGuardianContent(content, 8_000);

    expect(limited.length).toBeLessThanOrEqual(8_000);
    expect(limited.startsWith("BEGIN-")).toBe(true);
    expect(limited.endsWith("-END")).toBe(true);
    expect(limited).toContain("pominięto środkową część");
  });

  test("does not alter content already within the limit", () => {
    expect(limitGuardianContent("short message", 100)).toBe("short message");
  });
});

describe("Guardian verdict policy", () => {
  test.each([
    ["suspicious", 55, 0.95, "warn"],
    ["phishing", 39, 0.8, "hide"],
    ["phishing", 0, 0.8, "hide"],
    ["phishing", 39, 0.799, "warn"],
    ["phishing", 40, 0.99, "warn"],
    ["safe", 90, 0.99, "none"],
  ] as const)(
    "maps %s with score %i and confidence %f to %s",
    (guardianVerdict, trustScore, confidence, expectedAction) => {
      expect(
        getGuardianVerdictAction(
          verdict({ verdict: guardianVerdict, trustScore, confidence }),
        ),
      ).toBe(expectedAction);
    },
  );
});

describe("Guardian hidden block reconciliation", () => {
  const stable = {
    sameTarget: true,
    sameMessageKey: true,
    canAnalyze: true,
    canAutoHide: true,
    fingerprintMatches: true,
  } as const;

  test("keeps a hidden block when its identity and fingerprint still match", () => {
    expect(getHiddenBlockReconciliation(stable)).toBe("keep");
  });

  test("keeps a changed risky message hidden only while it is revalidated", () => {
    expect(
      getHiddenBlockReconciliation({
        ...stable,
        fingerprintMatches: false,
      }),
    ).toBe("revalidate-hidden");
  });

  test.each([
    ["target changed", { sameTarget: false }],
    ["message key changed", { sameMessageKey: false }],
    ["analysis is no longer allowed", { canAnalyze: false }],
    ["auto-hide is no longer safe", { canAutoHide: false }],
  ] as const)("restores the block when %s", (_label, changes) => {
    expect(
      getHiddenBlockReconciliation({ ...stable, ...changes }),
    ).toBe("restore");
  });
});
